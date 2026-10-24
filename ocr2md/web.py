"""Web UI cục bộ (Flask): tải PDF/ảnh lên, theo dõi tiến độ, sửa và tải Markdown."""
from __future__ import annotations

import copy
import io
import os
import re
import shutil
import tempfile
import threading
import time
import traceback
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from urllib.parse import quote, urlsplit

from flask import Flask, jsonify, request, send_from_directory

from . import ai as ai_mod
from . import config as config_mod
from .ocr import Cancelled, OcrError, Tesseract
from . import installer
from .inputs import detect_input
from .pipeline import ConvertResult, convert_file

MAX_UPLOAD_MB = 300
MAX_JOBS_KEPT = 20


@dataclass
class Job:
    id: str
    filename: str
    status: str = "queued"  # queued | running | done | error | cancelled
    stage: str = ""
    done: int = 0
    total: int = 0
    error: str = ""
    result: Optional[ConvertResult] = None
    images_dir: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)
    created: float = field(default_factory=time.time)


LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SETTING_TEXT_FIELDS = ("tesseract", "tessdata", "ai_provider", "ai_model", "ai_base_url", "ai_key_env")


def create_app(
    engine: Optional[Tesseract],
    *,
    engine_error: str = "",
    dpi: int = 300,
    workers: int = 0,
    ai_config: Optional[ai_mod.AiConfig] = None,
    settings: Optional[config_mod.Settings] = None,
    allowed_hosts: tuple[str, ...] = (),
) -> Flask:
    """Web vẫn mở khi chưa có Tesseract để người dùng tải hoặc chọn bản đã cài."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

    st = {
        "engine": engine,
        "engine_error": engine_error,
        "settings": settings or config_mod.Settings(),
        "ai": ai_config or ai_mod.AiConfig(),
    }

    @app.before_request
    def guard():
        # Web UI không có đăng nhập và có thể chạy chương trình (tesseract) theo cấu hình, nên chặn
        # trang web khác gọi vào localhost: (1) DNS rebinding -> kiểm tra Host; (2) CSRF -> kiểm tra Origin.
        host = urlsplit("//" + (request.host or "")).hostname or ""
        if host not in LOOPBACK and host not in allowed_hosts and "*" not in allowed_hosts:
            return jsonify(error="Host không hợp lệ."), 403
        origin = request.headers.get("Origin")
        if origin and request.method not in ("GET", "HEAD", "OPTIONS") and urlsplit(origin).netloc != request.host:
            return jsonify(error="Yêu cầu từ trang web khác bị chặn."), 403

    jobs: dict[str, Job] = {}
    jobs_lock = threading.Lock()
    run_lock = threading.Lock()  # mỗi lần chỉ chạy 1 job để không chiếm hết CPU/RAM
    download_state = {"status": "idle", "stage": "", "done": 0, "total": 0, "error": ""}
    download_lock = threading.Lock()

    def lang_options() -> list[str]:
        if not st["engine"]:
            return ["auto"]
        have = [l for l in st["engine"].langs if l != "osd" and not l.startswith("script/")]
        options = ["auto"]
        if {"vie", "eng"} <= set(have):
            options.append("vie+eng")
        options += sorted(have)
        return options

    def run_job(job: Job, input_path: str, workdir: str, opts: dict) -> None:
        with run_lock:
            try:
                if job.cancel.is_set():
                    job.status = "cancelled"
                    return
                job.status = "running"

                def progress(stage: str, done: int, total: int) -> None:
                    job.stage, job.done, job.total = stage, done, total

                job.result = convert_file(
                    input_path,
                    opts["engine"],
                    dpi=opts["dpi"],
                    workers=workers,
                    pages=opts["pages"],
                    page_markers=opts["page_markers"],
                    images_dir=job.images_dir or None,
                    image_prefix="images",
                    use_ai=opts["use_ai"],
                    ai_config=opts["ai"],
                    progress=progress,
                    cancelled=job.cancel.is_set,
                )
                job.status = "done"
            except Cancelled:
                job.status = "cancelled"
            except (OcrError, ai_mod.AiError) as exc:
                job.status, job.error = "error", str(exc)
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                job.status, job.error = "error", f"Lỗi không mong đợi: {exc}"
            finally:
                shutil.rmtree(workdir, ignore_errors=True)
                if job.status != "done":
                    shutil.rmtree(job.images_dir, ignore_errors=True)

    @app.get("/")
    def index():
        return INDEX_HTML

    @app.get("/api/config")
    def config():
        ok, why = ai_mod.check(st["ai"])
        eng = st["engine"]
        return jsonify(
            lang_options=lang_options(),
            dpi=dpi,
            ai_available=ok,
            ai_hint=why if not ok else ai_mod.describe(st["ai"]),
            warnings=eng.warnings if eng else [],
            engine_ok=eng is not None,
            engine_error=st["engine_error"],
            max_upload_mb=MAX_UPLOAD_MB,
        )

    # ---- Cài đặt ----
    def settings_payload() -> dict:
        s, eng = st["settings"], st["engine"]
        info = {"ok": eng is not None, "error": st["engine_error"]}
        if eng:
            info.update(cmd=eng.cmd, version=eng.version(), langs=sorted(eng.langs), tessdata=eng.tessdata or "", warnings=eng.warnings)
        return {
            **{k: getattr(s, k) for k in SETTING_TEXT_FIELDS},
            "ai_key_saved": bool(s.ai_api_key),  # không bao giờ trả key về trình duyệt
            "providers": ai_mod.PROVIDERS,
            "engine": info,
            "config_path": str(config_mod.config_path()),
        }

    @app.get("/api/settings")
    def get_settings():
        return jsonify(settings_payload())

    @app.post("/api/settings")
    def post_settings():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="Dữ liệu không hợp lệ."), 400
        new = copy.copy(st["settings"])
        for key in SETTING_TEXT_FIELDS:
            if key in data:
                value = data[key]
                if not isinstance(value, str) or len(value) > 500:
                    return jsonify(error=f"Giá trị '{key}' không hợp lệ."), 400
                setattr(new, key, value.strip().strip('"'))  # người dùng hay dán đường dẫn kèm dấu ngoặc kép
        old = st["settings"]
        if data.get("clear_ai_key"):
            new.ai_api_key = ""
        elif isinstance(data.get("ai_api_key"), str) and data["ai_api_key"].strip():
            new.ai_api_key = data["ai_api_key"].strip()
        elif (new.ai_provider, new.ai_base_url) != (old.ai_provider, old.ai_base_url):
            new.ai_api_key = ""  # đổi nơi nhận thì không mang key cũ theo, tránh gửi nhầm key sang bên khác
        if new.ai_provider and new.ai_provider not in ai_mod.PROVIDERS:
            return jsonify(error=f"Nhà cung cấp AI không hợp lệ: {new.ai_provider}"), 400
        if new.ai_base_url and urlsplit(new.ai_base_url).scheme not in ("http", "https"):
            return jsonify(error="URL API phải bắt đầu bằng http:// hoặc https://"), 400

        try:
            new_engine, new_error = Tesseract(new.tesseract or None, new.tessdata or None, "auto"), ""
        except OcrError as exc:
            if new.tesseract or new.tessdata:  # người dùng nhập thứ gì đó mà sai -> báo ngay, không lưu
                return jsonify(error=str(exc)), 400
            new_engine, new_error = None, str(exc)  # để trống và không tự tìm được: vẫn cho lưu phần AI
        try:
            config_mod.save(new)
        except OSError as exc:
            return jsonify(error=f"Không ghi được file cấu hình: {exc}"), 500
        st.update(settings=new, engine=new_engine, engine_error=new_error, ai=ai_mod.from_settings(new))
        return jsonify(settings_payload())

    @app.get("/api/tesseract/download")
    def download_status():
        with download_lock:
            return jsonify(download_state.copy())

    @app.post("/api/tesseract/download")
    def start_download():
        if os.name != "nt":
            return jsonify(error="Tải tự động hiện chỉ hỗ trợ Windows x64."), 400
        data = request.get_json(silent=True)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            return jsonify(error="Dữ liệu tải không hợp lệ."), 400
        url = str(data.get("url") or installer.INSTALLER_URL).strip()
        sha256 = str(data.get("sha256") or (installer.INSTALLER_SHA256 if url == installer.INSTALLER_URL else "")).strip()
        if len(sha256) != 64 or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
            return jsonify(error="Link tự chọn cần SHA-256 gồm 64 ký tự hex."), 400
        with download_lock:
            if download_state["status"] == "running":
                return jsonify(error="Tesseract đang được tải."), 409
            download_state.update(status="running", stage="installer", done=0, total=0, error="")

        def work():
            try:
                def progress(stage, done, total):
                    with download_lock:
                        download_state.update(stage=stage, done=done, total=total)
                exe, tessdata = installer.install(
                    config_mod.config_path().parent, progress, url=url, sha256=sha256
                )
                new_engine = Tesseract(exe, tessdata, "auto")
                new_settings = copy.copy(st["settings"])
                new_settings.tesseract, new_settings.tessdata = exe, tessdata
                config_mod.save(new_settings)
                st.update(settings=new_settings, engine=new_engine, engine_error="")
                with download_lock:
                    download_state["status"] = "done"
            except Exception as exc:
                with download_lock:
                    download_state.update(status="error", error=str(exc))

        threading.Thread(target=work, daemon=True).start()
        return jsonify(ok=True), 202

    @app.post("/api/settings/test-ai")
    def test_ai():
        try:
            return jsonify(ok=True, message=ai_mod.ping(st["ai"]))
        except ai_mod.AiError as exc:
            return jsonify(ok=False, message=str(exc))

    @app.post("/api/jobs")
    def create_job():
        upload = request.files.get("file")
        if not upload or not upload.filename:
            return jsonify(error="Chưa chọn file."), 400
        if st["engine"] is None:
            return jsonify(error="Chưa có Tesseract. Mở Cài đặt để tải hoặc chọn đường dẫn."), 400
        try:
            job_dpi = max(100, min(600, int(request.form.get("dpi", dpi))))
            job_engine = st["engine"].for_lang(request.form.get("lang", "auto"))
        except ValueError:
            return jsonify(error="DPI không hợp lệ."), 400
        except OcrError as exc:
            return jsonify(error=str(exc)), 400

        use_ai = request.form.get("ai") == "1"
        if use_ai:
            ok, why = ai_mod.check(st["ai"])
            if not ok:
                return jsonify(error=f"Không dùng được AI: {why}"), 400

        workdir = tempfile.mkdtemp(prefix="ocr2md_web_")
        input_path = str(Path(workdir) / "input")
        upload.save(input_path)
        try:
            detect_input(input_path)
        except OcrError as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            return jsonify(error=str(exc)), 400

        job = Job(id=uuid.uuid4().hex[:12], filename=Path(upload.filename).name)
        if request.form.get("images") == "1":
            job.images_dir = tempfile.mkdtemp(prefix="ocr2md_img_")
        with jobs_lock:
            jobs[job.id] = job
            for old in sorted(jobs.values(), key=lambda j: j.created)[:-MAX_JOBS_KEPT]:
                if old.status in ("done", "error", "cancelled"):
                    jobs.pop(old.id, None)
                    if old.images_dir:
                        shutil.rmtree(old.images_dir, ignore_errors=True)

        opts = dict(
            engine=job_engine,
            dpi=job_dpi,
            pages=request.form.get("pages", "").strip() or None,
            page_markers=request.form.get("page_markers") == "1",
            use_ai=use_ai,
            ai=st["ai"],
        )
        threading.Thread(target=run_job, args=(job, input_path, workdir, opts), daemon=True).start()
        return jsonify(id=job.id)

    def get_job(job_id: str) -> Optional[Job]:
        with jobs_lock:
            return jobs.get(job_id)

    @app.get("/api/jobs/<job_id>")
    def job_status(job_id: str):
        job = get_job(job_id)
        if not job:
            return jsonify(error="Không có tác vụ này."), 404
        return jsonify(status=job.status, stage=job.stage, done=job.done, total=job.total, error=job.error)

    @app.get("/api/jobs/<job_id>/result")
    def job_result(job_id: str):
        job = get_job(job_id)
        if not job or job.status != "done" or not job.result:
            return jsonify(error="Chưa có kết quả."), 404
        r = job.result
        return jsonify(
            markdown=r.markdown,
            markdown_ai=r.markdown_ai,
            warnings=r.warnings,
            pages=r.pages,
            lang=r.lang,
            images=r.images,
        )

    @app.get("/api/jobs/<job_id>/images/<name>")
    def job_image(job_id: str, name: str):
        job = get_job(job_id)
        if not job or not job.images_dir or not re.fullmatch(r"p\d{3}_fig\d{2}\.png", name):
            return jsonify(error="Không có ảnh này."), 404
        return send_from_directory(job.images_dir, name, mimetype="image/png")

    @app.post("/api/jobs/<job_id>/bundle")
    def job_bundle(job_id: str):
        """Đóng gói .md (đã sửa trong trình duyệt) cùng thư mục images/ thành zip."""
        job = get_job(job_id)
        payload = request.get_json(silent=True) or {}
        text = payload.get("markdown")
        if not job or not job.images_dir or not isinstance(text, str):
            return jsonify(error="Không có gì để đóng gói."), 404
        stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(payload.get("name") or "document"))[:80] or "document"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{stem}.md", text.encode("utf-8"))
            for img in sorted(Path(job.images_dir).glob("*.png")):
                z.write(img, f"images/{img.name}")
        buf.seek(0)
        return app.response_class(
            buf.getvalue(),
            mimetype="application/zip",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(stem)}.zip"},
        )

    @app.post("/api/jobs/<job_id>/cancel")
    def job_cancel(job_id: str):
        job = get_job(job_id)
        if not job:
            return jsonify(error="Không có tác vụ này."), 404
        job.cancel.set()
        return jsonify(ok=True)

    return app


INDEX_HTML = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OCR2MD</title>
<style>
:root{--bg:#f6f5f1;--fg:#1d2127;--muted:#667085;--card:#fff;--line:#e2dfd7;--accent:#2f5fd0;--accent-fg:#fff;--bad:#b42318;--warn:#8a5a00;--code:#f1efe9}
@media (prefers-color-scheme:dark){:root{--bg:#15171b;--fg:#e7e9ec;--muted:#98a2ae;--card:#1d2025;--line:#2d3239;--accent:#6f9bff;--accent-fg:#0b1020;--bad:#ff8f84;--warn:#f0c36a;--code:#262a31}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;justify-content:space-between}
header h1{margin:0;font-size:18px;font-weight:650}
header p{margin:2px 0 0;color:var(--muted);font-size:13px}
main{display:grid;grid-template-columns:minmax(260px,300px) minmax(0,1fr);gap:18px;padding:18px 24px;max-width:1440px;margin:0 auto}
@media (max-width:850px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
label{display:block;font-size:13px;color:var(--muted);margin:12px 0 4px}
input[type=text],input[type=password],select{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:7px;background:var(--bg);color:var(--fg);font:inherit}
.drop{border:2px dashed var(--line);border-radius:10px;padding:20px;text-align:center;color:var(--muted);cursor:pointer}
.drop.over{border-color:var(--accent);color:var(--fg)}
.drop strong{display:block;color:var(--fg);word-break:break-all}
.row{display:flex;gap:8px;align-items:center;margin-top:10px}
.row label{margin:0;color:var(--fg)}
button{font:inherit;padding:8px 14px;border-radius:7px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
button.primary{background:var(--accent);color:var(--accent-fg);border-color:transparent;font-weight:600}
button:disabled{opacity:.5;cursor:not-allowed}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin-top:14px}
.bar>i{display:block;height:100%;width:0;background:var(--accent);transition:width .3s}
#status{margin-top:8px;font-size:13px;color:var(--muted);min-height:20px}
#status.bad{color:var(--bad)}
.notes{margin:12px 0 0;padding:0;list-style:none;font-size:13px;color:var(--warn)}
.notes li{margin-top:6px}
.hint{font-size:12px;color:var(--muted);margin-top:3px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.toolbar .sp{flex:1}
.tab.on{background:var(--accent);color:var(--accent-fg);border-color:transparent}
.panes{min-width:0}
textarea{width:100%;height:68vh;padding:12px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);font:13px/1.55 ui-monospace,Consolas,monospace;resize:vertical}
#preview{height:68vh;overflow:auto;padding:12px 20px;border:1px solid var(--line);border-radius:8px}
#preview h1,#preview h2,#preview h3{line-height:1.3}
#preview .pg{margin:18px 0 6px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);border-top:1px dashed var(--line);padding-top:6px}
.empty{color:var(--muted);text-align:center;padding:80px 0}
dialog{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:12px;padding:20px 22px;width:min(520px,92vw);max-height:88vh;overflow-y:auto}
dialog::backdrop{background:rgba(0,0,0,.45)}
dialog h2{margin:0 0 4px;font-size:17px}
dialog h3{margin:18px 0 0;font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
#engInfo,#sStatus{font-size:13px;margin-top:6px;word-break:break-word}
#engInfo.ok,#sStatus.ok{color:var(--fg)}
#engInfo.bad,#sStatus.bad{color:var(--bad)}
.dialog-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}
.dialog-head h2{margin:0}
.dialog-head button{padding:4px 9px}
details.advanced{border-top:1px solid var(--line);margin-top:16px;padding-top:12px}
details.advanced summary{cursor:pointer;color:var(--muted);font-size:13px;user-select:none}
details.advanced[open] summary{color:var(--fg);margin-bottom:10px}
details.advanced .inner{padding:0 2px 4px}
.actions{display:flex;gap:8px;align-items:center;margin-top:16px}
.actions .primary{flex:1}
[hidden]{display:none!important}
</style>
</head>
<body>
<header>
  <h1>OCR2MD</h1>
  <button type="button" id="openSettings">⚙ Cài đặt</button>
</header>
<main>
  <section class="card">
    <form id="form">
      <div class="drop" id="drop"><span id="dropText">Kéo thả PDF hoặc ảnh<br>hoặc bấm để chọn</span></div>
      <input type="file" id="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.gif" hidden>
      <label for="lang">Ngôn ngữ</label>
      <select id="lang"></select>
      <details class="advanced" id="convertAdvanced">
        <summary>Tùy chọn nâng cao</summary>
        <div class="inner">
          <label for="dpi">Độ phân giải PDF</label>
          <select id="dpi"><option>200</option><option>300</option><option>400</option><option>600</option></select>
          <label for="pages">Chỉ xử lý trang/frame</label>
          <input type="text" id="pages" placeholder="Ví dụ: 1-5,8">
          <div class="row"><input type="checkbox" id="images"><label for="images">Tách hình</label></div>
          <div class="row"><input type="checkbox" id="markers"><label for="markers">Đánh dấu trang trong Markdown</label></div>
          <div class="row"><input type="checkbox" id="ai"><label for="ai">AI hiệu đính</label></div>
          <div class="hint" id="aiHint"></div>
          <button type="button" id="openAiSettings">Thiết lập AI</button>
        </div>
      </details>
      <div class="actions">
        <button class="primary" id="go" type="submit">Chuyển đổi</button>
        <button type="button" id="cancel" hidden>Huỷ</button>
      </div>
      <div class="bar" id="progress" hidden><i id="bar"></i></div>
      <div id="status" role="status" aria-live="polite"></div>
      <ul class="notes" id="notes"></ul>
    </form>
  </section>
  <section class="card">
    <div class="toolbar" id="toolbar" hidden>
      <button class="tab on" id="tabRaw" type="button">Bản OCR</button>
      <button class="tab" id="tabAi" type="button" hidden>Bản AI</button>
      <span class="sp"></span>
      <button id="edit" type="button">Sửa</button>
      <button id="copy" type="button">Sao chép</button>
      <button class="primary" id="download" type="button">Tải .md</button>
    </div>
    <div class="panes" id="panes" hidden>
      <div id="preview"></div>
      <textarea id="editor" spellcheck="false" aria-label="Nội dung Markdown" hidden></textarea>
    </div>
    <div class="empty" id="empty">Markdown sẽ hiện ở đây.</div>
  </section>
</main>
<dialog id="dlg">
  <div class="dialog-head"><h2>Cài đặt</h2><button type="button" id="sClose" aria-label="Đóng">✕</button></div>
  <div id="engInfo" role="status"></div>
  <div class="actions"><button type="button" class="primary" id="sDownload">Tải Tesseract</button></div>
  <div class="bar" id="sDownloadProgress" hidden><i id="sDownloadBar"></i></div>
  <div id="sDownloadStatus" class="hint" aria-live="polite"></div>
  <label for="s_tess">Hoặc dùng Tesseract đã cài</label>
  <input type="text" id="s_tess" placeholder="Đường dẫn tesseract.exe hoặc thư mục cài đặt" autocomplete="off">
  <details class="advanced" id="sAdvanced">
    <summary>Nâng cao</summary>
    <div class="inner">
      <h3>Tesseract</h3>
      <div id="sEnginePath" class="hint"></div>
      <label for="s_tdata">Thư mục tessdata</label>
      <input type="text" id="s_tdata" autocomplete="off">
      <label for="s_tess_url">Link tải bộ cài khác</label>
      <input type="url" id="s_tess_url" placeholder="HTTPS, để trống để dùng bản đề xuất" autocomplete="off">
      <label for="s_tess_sha">SHA-256 của link tự chọn</label>
      <input type="text" id="s_tess_sha" placeholder="64 ký tự hex" autocomplete="off">
      <h3>AI hiệu đính</h3>
      <label for="s_prov">Nhà cung cấp</label>
      <select id="s_prov"></select>
      <label for="s_model">Model</label>
      <input type="text" id="s_model" placeholder="Để trống để dùng mặc định" autocomplete="off">
      <div id="urlRow">
        <label for="s_url">URL API</label>
        <input type="text" id="s_url" placeholder="http://localhost:11434/v1" autocomplete="off">
      </div>
      <label for="s_key">API key</label>
      <input type="password" id="s_key" autocomplete="off">
      <div class="row"><input type="checkbox" id="s_clear"><label for="s_clear">Xoá key đã lưu</label></div>
      <div class="hint" id="keyHint"></div>
      <div class="hint">Key được lưu dạng văn bản thường. Đổi nhà cung cấp hoặc URL sẽ xoá key cũ nếu không nhập key mới.</div>
      <button type="button" id="sTest">Lưu và kiểm tra AI</button>
      <div class="hint" id="cfgPath"></div>
    </div>
  </details>
  <div id="sStatus" role="status" aria-live="polite"></div>
  <div class="actions"><button type="button" class="primary" id="sSave">Lưu cài đặt</button></div>
</dialog>
<script>
const $ = s => document.querySelector(s);
const state = {jobId: null, timer: null, texts: {raw: "", ai: null}, view: "raw", name: "document", images: 0};
const STAGES = {ocr: "Đang OCR", format: "Đang biên tập", ai: "AI đang hiệu đính"};

function setStatus(msg, bad) { const el = $("#status"); el.textContent = msg; el.className = bad ? "bad" : ""; }
function setNotes(list) { $("#notes").innerHTML = ""; list.forEach(t => { const li = document.createElement("li"); li.textContent = "⚠ " + t; $("#notes").append(li); }); }
function setBusy(b) { $("#go").disabled = b; $("#cancel").hidden = !b; $("#progress").hidden = !b; }

function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function inline(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>"); }
function unescapeMd(s) { return s.replace(/^\\(?=[#>*+\-])/, "").replace(/^(\d+)\\([.)])/, "$1$2"); }

function imgSrc(p) { return /^images\//.test(p) ? "/api/jobs/" + state.jobId + "/" + p : ""; }

function renderMd(md) {
  const out = []; let list = null, para = [];
  const flushPara = () => { if (para.length) { out.push("<p>" + inline(para.join(" ")) + "</p>"); para = []; } };
  const flushList = () => { if (list) { out.push("<" + list.t + ">" + list.items.map(i => "<li>" + inline(i) + "</li>").join("") + "</" + list.t + ">"); list = null; } };
  for (const raw of md.split("\n")) {
    const line = raw.trimEnd(); let m;
    if (!line.trim()) { flushPara(); flushList(); continue; }
    if ((m = line.match(/^<!--\s*page\s+(\d+)\s*-->$/))) { flushPara(); flushList(); out.push('<div class="pg">trang ' + m[1] + "</div>"); continue; }
    if ((m = line.match(/^!\[([^\]]*)\]\(([^)\s]+)\)$/))) { flushPara(); flushList(); const src = decodeURIComponent(m[2]); out.push(imgSrc(src) ? '<figure><img src="' + esc(imgSrc(src)) + '" alt="' + esc(m[1]) + '" style="max-width:100%"></figure>' : "<p>🖼 " + esc(m[1]) + "</p>"); continue; }
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) { flushPara(); flushList(); out.push("<h" + m[1].length + ">" + inline(m[2]) + "</h" + m[1].length + ">"); continue; }
    if ((m = line.match(/^[-*]\s+(.*)$/))) { flushPara(); if (!list || list.t !== "ul") { flushList(); list = {t: "ul", items: []}; } list.items.push(m[1]); continue; }
    if ((m = line.match(/^\d+\.\s+(.*)$/))) { flushPara(); if (!list || list.t !== "ol") { flushList(); list = {t: "ol", items: []}; } list.items.push(m[1]); continue; }
    flushList(); para.push(unescapeMd(line));
  }
  flushPara(); flushList();
  return out.join("");
}

let renderTimer = null;
function refreshPreview() { clearTimeout(renderTimer); renderTimer = setTimeout(() => { $("#preview").innerHTML = renderMd($("#editor").value); }, 150); }
function setEditing(editing) {
  $("#editor").hidden = !editing;
  $("#preview").hidden = editing;
  $("#edit").textContent = editing ? "Xem trước" : "Sửa";
  if (!editing) refreshPreview();
}

function showView(view) {
  if (state.view) state.texts[state.view] = $("#editor").value;  // lưu chỗ người dùng đã sửa của tab đang xem
  state.view = view;
  $("#editor").value = state.texts[view];
  $("#tabRaw").classList.toggle("on", view === "raw");
  $("#tabAi").classList.toggle("on", view === "ai");
  refreshPreview();
}

async function loadResult() {
  const r = await fetch("/api/jobs/" + state.jobId + "/result");
  const j = await r.json();
  if (!r.ok) { setStatus(j.error || "Không lấy được kết quả.", true); return; }
  state.texts = {raw: j.markdown, ai: j.markdown_ai};
  state.images = j.images || 0;
  state.view = null;  // kết quả mới: đừng lưu nội dung ô soạn thảo cũ đè lên
  $("#tabAi").hidden = j.markdown_ai === null;
  $("#empty").hidden = true; $("#toolbar").hidden = false; $("#panes").hidden = false;
  setEditing(false);
  showView(j.markdown_ai !== null ? "ai" : "raw");
  setNotes(j.warnings);
  setStatus("Xong: " + j.pages + " trang, ngôn ngữ " + j.lang + (state.images ? ", " + state.images + " hình" : "") + ".");
  $("#download").textContent = state.images ? "Tải .zip (md + hình)" : "Tải .md";
}

function poll() {
  clearInterval(state.timer);
  state.timer = setInterval(async () => {
    let j;
    try { j = await (await fetch("/api/jobs/" + state.jobId)).json(); } catch (e) { return; }
    $("#bar").style.width = (j.total ? Math.round(100 * j.done / j.total) : 0) + "%";
    if (j.status === "queued") setStatus("Đang chờ…");
    else if (j.status === "running") setStatus((STAGES[j.stage] || "Đang xử lý") + (j.total > 1 ? " " + j.done + "/" + j.total : "…"));
    if (["done", "error", "cancelled"].includes(j.status)) {
      clearInterval(state.timer); setBusy(false);
      if (j.status === "done") { $("#bar").style.width = "100%"; await loadResult(); }
      else setStatus(j.status === "error" ? j.error : "Đã huỷ.", j.status === "error");
    }
  }, 700);
}

async function init() {
  const cfg = await (await fetch("/api/config")).json();
  const prevLang = $("#lang").value || "auto";
  $("#lang").innerHTML = "";
  const langNames = {auto: "Tự động", "vie+eng": "Tiếng Việt + Anh", vie: "Tiếng Việt", eng: "Tiếng Anh"};
  cfg.lang_options.forEach(l => $("#lang").add(new Option(langNames[l] || l, l)));
  $("#lang").value = cfg.lang_options.includes(prevLang) ? prevLang : "auto";
  $("#dpi").value = $("#dpi").dataset.set ? $("#dpi").value : String(cfg.dpi);
  $("#dpi").dataset.set = "1";
  $("#ai").disabled = !cfg.ai_available;
  if (!cfg.ai_available) $("#ai").checked = false;
  $("#aiHint").textContent = cfg.ai_available ? cfg.ai_hint : "Chưa cấu hình AI.";
  $("#go").disabled = !cfg.engine_ok;
  setNotes(cfg.warnings);
  if (!cfg.engine_ok) { setStatus("Chưa có Tesseract. Mở Cài đặt để tải.", true); openSettings(); }
  else if ($("#status").classList.contains("bad")) setStatus("");
}

// ---- Cài đặt ----
async function api(path, body) {
  const opts = body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
  const r = await fetch(path, opts);
  return {ok: r.ok, j: await r.json()};
}
function sStatus(msg, bad) { const el = $("#sStatus"); el.textContent = msg; el.className = bad ? "bad" : "ok"; }
function urlRowVisible() { return ["openai", "ollama", "custom"].includes($("#s_prov").value) || $("#s_url").value.trim() !== ""; }
function fillSettings(s) {
  if (!$("#s_prov").options.length) {
    $("#s_prov").add(new Option("(mặc định: deepseek)", ""));
    s.providers.forEach(p => $("#s_prov").add(new Option(p, p)));
  }
  $("#s_tess").value = s.tesseract; $("#s_tdata").value = s.tessdata;
  $("#s_prov").value = s.ai_provider; $("#s_model").value = s.ai_model; $("#s_url").value = s.ai_base_url;
  $("#s_key").value = ""; $("#s_clear").checked = false;
  $("#urlRow").hidden = !urlRowVisible();
  $("#keyHint").textContent = s.ai_key_saved ? "Đã có key được lưu. Để trống ô trên để giữ nguyên." : "Chưa lưu key (có thể dùng biến môi trường).";
  $("#cfgPath").textContent = "File cấu hình: " + s.config_path;
  const e = s.engine, info = $("#engInfo");
  if (e.ok) {
    const langs = e.langs.filter(l => l !== "osd");
    info.className = "ok";
    info.textContent = "✔ Tesseract sẵn sàng · " + langs.join(", ") + (langs.includes("vie") ? "" : " · thiếu tiếng Việt");
    $("#sEnginePath").textContent = e.version + " · " + e.cmd;
  } else {
    info.className = "bad"; info.textContent = "Chưa có Tesseract. Tải xuống hoặc chọn bản đã cài.";
    $("#sEnginePath").textContent = e.error || "";
  }
}
let downloadTimer = null;
const DOWNLOAD_STAGE = {installer: "Đang tải Tesseract", extract: "Đang giải nén", eng: "Đang tải tiếng Anh", vie: "Đang tải tiếng Việt", osd: "Đang tải nhận hướng trang", complete: "Hoàn tất"};
async function refreshDownload() {
  const {j} = await api("/api/tesseract/download");
  const label = DOWNLOAD_STAGE[j.stage] || "";
  const pct = j.total ? Math.round(100 * j.done / j.total) : 0;
  $("#sDownloadProgress").hidden = j.status !== "running";
  $("#sDownloadBar").style.width = pct + "%";
  $("#sDownloadStatus").textContent = j.status === "error" ? j.error : (j.status === "running" ? label + (j.total ? " " + pct + "%" : "…") : (j.status === "done" ? "Tesseract đã sẵn sàng." : ""));
  $("#sDownload").disabled = j.status === "running";
  if (j.status !== "running" && downloadTimer) {
    clearInterval(downloadTimer); downloadTimer = null;
    if (j.status === "done") {
      const settings = await api("/api/settings");
      fillSettings(settings.j);
      await init();
    }
  }
}
async function openSettings() {
  const {j} = await api("/api/settings");
  fillSettings(j); sStatus(""); await refreshDownload();
  if (!$("#dlg").open) $("#dlg").showModal();
}
async function saveSettings() {
  const body = {
    tesseract: $("#s_tess").value, tessdata: $("#s_tdata").value, ai_provider: $("#s_prov").value,
    ai_model: $("#s_model").value, ai_base_url: $("#urlRow").hidden ? "" : $("#s_url").value,
    ai_api_key: $("#s_key").value, clear_ai_key: $("#s_clear").checked,
  };
  const {ok, j} = await api("/api/settings", body);
  if (!ok) { sStatus(j.error || "Không lưu được.", true); return false; }
  fillSettings(j); await init(); sStatus("Đã lưu.");
  return true;
}
$("#sDownload").onclick = async () => {
  const url = $("#s_tess_url").value.trim(), sha256 = $("#s_tess_sha").value.trim();
  const {ok, j} = await api("/api/tesseract/download", {url, sha256});
  if (!ok) { $("#sDownloadStatus").textContent = j.error || "Không bắt đầu tải được."; return; }
  await refreshDownload();
  if (!downloadTimer) downloadTimer = setInterval(refreshDownload, 350);
};
$("#openSettings").onclick = openSettings;
$("#openAiSettings").onclick = async () => { await openSettings(); $("#sAdvanced").open = true; };
$("#sClose").onclick = () => $("#dlg").close();
$("#sSave").onclick = saveSettings;
$("#sTest").onclick = async () => {
  if (!(await saveSettings())) return;
  sStatus("Đang kiểm tra AI…");
  const {j} = await api("/api/settings/test-ai", {});
  sStatus((j.ok ? "✔ " : "✖ ") + j.message, !j.ok);
};
$("#s_prov").onchange = () => { $("#urlRow").hidden = !urlRowVisible(); };

const drop = $("#drop"), fileInput = $("#file");
function pick(f) { if (f) { state.name = f.name.replace(/\.[^.]+$/i, ""); $("#dropText").innerHTML = "<strong></strong>"; $("#dropText strong").textContent = f.name; } }
drop.onclick = () => fileInput.click();
fileInput.onchange = () => pick(fileInput.files[0]);
drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files[0]) { fileInput.files = e.dataTransfer.files; pick(fileInput.files[0]); } };

$("#form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = fileInput.files[0];
  if (!f) { setStatus("Chọn một file PDF hoặc ảnh trước.", true); return; }
  const fd = new FormData();
  fd.append("file", f); fd.append("lang", $("#lang").value); fd.append("dpi", $("#dpi").value);
  fd.append("pages", $("#pages").value); fd.append("page_markers", $("#markers").checked ? "1" : "0");
  fd.append("ai", $("#ai").checked ? "1" : "0"); fd.append("images", $("#images").checked ? "1" : "0");
  setBusy(true); setNotes([]); setStatus("Đang tải lên…"); $("#bar").style.width = "0";
  try {
    const r = await fetch("/api/jobs", {method: "POST", body: fd});
    const j = await r.json();
    if (!r.ok) { setBusy(false); setStatus(j.error || "Lỗi tải lên.", true); return; }
    state.jobId = j.id; poll();
  } catch (err) { setBusy(false); setStatus("Không kết nối được máy chủ.", true); }
});
$("#cancel").onclick = () => fetch("/api/jobs/" + state.jobId + "/cancel", {method: "POST"});
$("#tabRaw").onclick = () => showView("raw");
$("#tabAi").onclick = () => showView("ai");
$("#edit").onclick = () => setEditing($("#editor").hidden);
$("#editor").addEventListener("input", refreshPreview);
$("#copy").onclick = async () => { await navigator.clipboard.writeText($("#editor").value); setStatus("Đã sao chép."); };
function save(blob, filename) {
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
$("#download").onclick = async () => {
  const text = $("#editor").value;
  if (!state.images) return save(new Blob([text], {type: "text/markdown;charset=utf-8"}), state.name + ".md");
  const r = await fetch("/api/jobs/" + state.jobId + "/bundle", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({markdown: text, name: state.name})});
  if (!r.ok) { setStatus("Không đóng gói được.", true); return; }
  save(await r.blob(), state.name + ".zip");
};
init();
</script>
</body>
</html>
"""
