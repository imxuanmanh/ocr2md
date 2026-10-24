from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__
from . import ai as ai_mod
from . import config as config_mod
from .ocr import Cancelled, OcrError, Tesseract
from .pipeline import convert_file

STAGE_LABEL = {"ocr": "OCR", "format": "Biên tập", "ai": "AI hiệu đính"}


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _add_engine_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--tesseract", help="tesseract.exe hoặc thư mục Tesseract-OCR (hoặc biến TESSERACT_CMD)")
    p.add_argument("--tessdata", help="thư mục tessdata (mặc định: thư mục tessdata cạnh tesseract)")
    p.add_argument("--lang", default="auto", help="ví dụ vie+eng; 'auto' = vie+eng nếu có, không thì eng")
    p.add_argument("--dpi", type=int, default=300, help="độ phân giải render trang (mặc định 300)")
    p.add_argument("--psm", type=int, default=3, help="chế độ phân đoạn trang của tesseract (mặc định 3)")
    p.add_argument("--workers", type=int, default=0, help="số tiến trình OCR song song (0 = tự chọn)")


def _add_ai_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--ai-provider", choices=ai_mod.PROVIDERS, help=f"mặc định {ai_mod.DEFAULT_PROVIDER} (hoặc biến OCR2MD_AI_PROVIDER)")
    p.add_argument("--ai-model", help="tên model (hoặc biến OCR2MD_AI_MODEL); mặc định theo nhà cung cấp")
    p.add_argument("--ai-base-url", help="URL API tương thích OpenAI, ví dụ http://localhost:11434/v1")
    p.add_argument("--ai-key-env", help="tên biến môi trường chứa API key (mặc định theo nhà cung cấp)")


def _ai_config(a: argparse.Namespace, saved: config_mod.Settings | None = None) -> ai_mod.AiConfig:
    """Thứ tự ưu tiên: cờ dòng lệnh > cấu hình đã lưu (⚙ Cài đặt) > biến môi trường > mặc định."""
    s = saved or config_mod.load()
    provider = a.ai_provider or s.ai_provider or None
    base_url = a.ai_base_url or s.ai_base_url or None
    # Key đã lưu chỉ dùng khi đích gửi không đổi so với lúc lưu, tránh gửi key của bên này sang bên khác.
    same_target = (provider or ai_mod.DEFAULT_PROVIDER) == (s.ai_provider or ai_mod.DEFAULT_PROVIDER) and (
        base_url or ""
    ) == (s.ai_base_url or "")
    return ai_mod.AiConfig(
        provider,
        a.ai_model or s.ai_model or None,
        base_url,
        a.ai_key_env or s.ai_key_env or None,
        (s.ai_api_key or None) if same_target else None,
    )


def _tesseract_args(a: argparse.Namespace, saved: config_mod.Settings | None = None) -> tuple[str | None, str | None]:
    s = saved or config_mod.load()
    cmd = a.tesseract or os.environ.get("TESSERACT_CMD") or s.tesseract or None
    return cmd, a.tessdata or s.tessdata or None


def _make_engine(a: argparse.Namespace) -> Tesseract:
    engine = Tesseract(*_tesseract_args(a), a.lang, psm=a.psm)
    for warning in engine.warnings:
        print(f"⚠ {warning}", file=sys.stderr)
    return engine


def cmd_convert(a: argparse.Namespace) -> int:
    source = Path(a.input)
    if not source.is_file():
        print(f"Không thấy file: {source}", file=sys.stderr)
        return 2
    ai_config = _ai_config(a)
    if a.ai:
        ok, why = ai_mod.check(ai_config)
        if not ok:
            print(f"Không dùng được --ai: {why}", file=sys.stderr)
            return 2
        print(f"Lưu ý: {ai_mod.describe(ai_config)}", file=sys.stderr)

    engine = _make_engine(a)

    def progress(stage: str, done: int, total: int) -> None:
        sys.stderr.write(f"\r{STAGE_LABEL.get(stage, stage)}: {done}/{total}   ")
        if done >= total:
            sys.stderr.write("\n")
        sys.stderr.flush()

    out = Path(a.output) if a.output else source.with_suffix(".md")
    images_dir = prefix = None
    if a.extract_images or a.images_dir:
        images_dir = Path(a.images_dir) if a.images_dir else out.with_name(out.stem + "_images")
        try:  # link tương đối với file .md để mở được ở bất kỳ đâu
            prefix = images_dir.resolve().relative_to(out.resolve().parent).as_posix()
        except ValueError:
            prefix = images_dir.resolve().as_uri()  # thư mục ảnh nằm ngoài thư mục .md
        images_dir = str(images_dir)

    result = convert_file(
        str(source),
        engine,
        dpi=a.dpi,
        workers=a.workers,
        pages=a.pages,
        page_markers=a.page_markers,
        images_dir=images_dir,
        image_prefix=prefix or "images",
        use_ai=a.ai,
        ai_config=ai_config,
        progress=progress,
    )
    for warning in result.warnings:
        if warning not in engine.warnings:
            print(f"⚠ {warning}", file=sys.stderr)

    out.write_text(result.markdown_ai or result.markdown, encoding="utf-8", newline="\n")
    if result.markdown_ai and a.keep_raw:
        raw = out.with_name(out.stem + ".raw.md")
        raw.write_text(result.markdown, encoding="utf-8", newline="\n")
        print(f"Bản chưa qua AI: {raw}", file=sys.stderr)
    extra = f", {result.images} hình -> {images_dir}" if images_dir else ""
    print(f"Đã ghi {out} ({result.pages} trang/frame, ngôn ngữ {result.lang}{extra})")
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    from .web import create_app

    if a.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            "⚠ Web UI không có đăng nhập. Đang nghe ở địa chỉ không phải loopback: chỉ nên như vậy trong Docker "
            "(và publish cổng về 127.0.0.1) hoặc mạng tin cậy.",
            file=sys.stderr,
        )
    saved = config_mod.load()
    try:
        engine, engine_error = Tesseract(*_tesseract_args(a, saved), a.lang, psm=a.psm), ""
        for warning in engine.warnings:
            print(f"⚠ {warning}", file=sys.stderr)
    except OcrError as exc:  # vẫn mở web để người dùng chỉ đường dẫn trong ⚙ Cài đặt
        engine, engine_error = None, str(exc)
        print(f"⚠ {exc}\n  Mở ⚙ Cài đặt để tải Tesseract hoặc chọn bản đã cài.", file=sys.stderr)
    app = create_app(
        engine,
        engine_error=engine_error,
        dpi=a.dpi,
        workers=a.workers,
        ai_config=_ai_config(a, saved),
        settings=saved,
        allowed_hosts=tuple(h.lower() for h in a.allowed_host),
    )
    url = f"http://{'localhost' if a.host in ('0.0.0.0', '::') else a.host}:{a.port}"
    print(f"Web UI: {url}  (Ctrl+C để dừng)")
    if not a.no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    app.run(host=a.host, port=a.port, threaded=True, debug=False)
    return 0


def cmd_doctor(a: argparse.Namespace) -> int:
    engine = Tesseract(*_tesseract_args(a), a.lang, psm=a.psm)
    print(f"cấu hình  : {config_mod.config_path()}")
    print(f"tesseract : {engine.cmd}")
    print(f"phiên bản : {engine.version()}")
    print(f"tessdata  : {engine.tessdata or '(mặc định / TESSDATA_PREFIX)'}")
    print(f"ngôn ngữ  : {', '.join(sorted(engine.langs))}")
    print(f"sẽ OCR với: {engine.lang}")
    for warning in engine.warnings:
        print(f"⚠ {warning}")
    try:
        from .ocr import _import_pymupdf

        print(f"pymupdf   : {_import_pymupdf().__name__} OK")
    except OcrError as exc:
        print(f"pymupdf   : {exc}")
    cfg = _ai_config(a)
    ok, why = ai_mod.check(cfg)
    ai_line = ai_mod.describe(cfg).removeprefix("AI: ") if ok else "chưa bật — " + why
    print(f"AI        : {ai_line}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ocr2md", description="OCR PDF và ảnh bằng Tesseract thành Markdown.")
    parser.add_argument("--version", action="version", version=f"ocr2md {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("convert", help="chuyển PDF hoặc ảnh thành Markdown")
    p.add_argument("input", help="file PDF hoặc ảnh")
    p.add_argument("-o", "--output", help="file .md đầu ra (mặc định: cạnh file đầu vào)")
    p.add_argument("--pages", help="chỉ xử lý các trang này, ví dụ 1-3,5")
    p.add_argument("--extract-images", action="store_true", help="tách hình ra thư mục <tên>_images và chèn link vào .md")
    p.add_argument("--images-dir", help="thư mục lưu hình (tự bật --extract-images)")
    p.add_argument("--page-markers", action="store_true", help="chèn <!-- page N --> trước mỗi trang")
    p.add_argument("--ai", action="store_true", help="hiệu đính bằng AI (mặc định DeepSeek, cần DEEPSEEK_API_KEY)")
    _add_ai_args(p)
    p.add_argument("--keep-raw", action="store_true", help="khi dùng --ai, lưu thêm bản chưa qua AI (*.raw.md)")
    _add_engine_args(p)
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("serve", help="chạy web UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="không tự mở trình duyệt")
    p.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        metavar="TÊN",
        help="tên host được phép trong URL, ngoài localhost/127.0.0.1 (lặp lại được; '*' = bỏ kiểm tra, chỉ dùng sau reverse proxy)",
    )
    _add_ai_args(p)
    _add_engine_args(p)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("doctor", help="kiểm tra tesseract, ngôn ngữ và thư viện")
    _add_engine_args(p)
    _add_ai_args(p)
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OcrError, ai_mod.AiError) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 1
    except Cancelled:
        print("Đã huỷ.", file=sys.stderr)
        return 130
    except KeyboardInterrupt:
        print("\nĐã dừng.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
