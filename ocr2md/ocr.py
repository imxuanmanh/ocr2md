"""PDF/ảnh -> Tesseract (TSV) -> các dòng chữ kèm toạ độ.

Gọi thẳng tesseract bằng subprocess (không cần pytesseract) và render trang
bằng PyMuPDF (không cần poppler), nên trên Windows chỉ cần trỏ tới
tesseract.exe là chạy được.
"""
from __future__ import annotations

import copy
import csv
import io
import os
import re
import shutil
import statistics
import subprocess
import tempfile
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


class OcrError(RuntimeError):
    """Lỗi có thể giải thích thẳng cho người dùng."""


class Cancelled(Exception):
    """Người dùng huỷ tác vụ."""


@dataclass
class Line:
    block: int
    par: int
    text: str
    top: int
    bottom: int
    left: int
    height: float  # chiều cao "đại diện" của chữ trong dòng
    conf: float
    right: int = 0
    words: list[tuple[int, int, int, int, float]] = field(default_factory=list)  # (left, top, w, h, conf)


@dataclass
class Figure:
    left: int  # toạ độ pixel trên trang đã render
    top: int
    right: int
    bottom: int
    alt: str = ""  # chú thích "Hình 3..." nếu tìm được gần đó
    file: str = ""  # tên file PNG đã lưu, tương đối với thư mục ảnh


@dataclass
class Page:
    number: int  # đánh số từ 1
    width: int
    height: int
    lines: list[Line] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)


# --------------------------------------------------------------------------
# Tìm và chạy tesseract
# --------------------------------------------------------------------------

def _exe_name() -> str:
    return "tesseract.exe" if os.name == "nt" else "tesseract"


def find_tesseract(explicit: Optional[str] = None) -> str:
    for candidate in (explicit, os.environ.get("TESSERACT_CMD")):
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_dir():  # cho phép trỏ vào thư mục Tesseract-OCR
            path = path / _exe_name()
        if path.is_file():
            # Đường dẫn có thể đến từ giao diện web nên chỉ chấp nhận đúng tên chương trình tesseract.
            if path.stem.lower() != "tesseract":
                raise OcrError(f"'{path.name}' không phải tesseract (tên file phải là tesseract hoặc tesseract.exe).")
            return str(path)
        raise OcrError(f"Không tìm thấy tesseract tại: {candidate}")

    found = shutil.which("tesseract")
    if found:
        return found
    if os.name == "nt":
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if base:
                path = Path(base) / "Tesseract-OCR" / "tesseract.exe"
                if path.is_file():
                    return str(path)
    raise OcrError(
        "Không tìm thấy Tesseract trên hệ thống. Dùng --tesseract <đường dẫn tesseract.exe hoặc thư mục "
        "Tesseract-OCR>, hoặc đặt biến môi trường TESSERACT_CMD."
    )


def resolve_tessdata(cmd: str, explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    if os.environ.get("TESSDATA_PREFIX"):
        return None  # tesseract tự đọc biến này
    sibling = Path(cmd).resolve().parent / "tessdata"
    return str(sibling) if sibling.is_dir() else None


_LANG_LINE = re.compile(r"^[\w/]+$")


class Tesseract:
    def __init__(
        self,
        cmd: Optional[str] = None,
        tessdata: Optional[str] = None,
        lang: str = "auto",
        psm: int = 3,
        timeout: int = 300,
    ):
        self.cmd = find_tesseract(cmd)
        self.tessdata = resolve_tessdata(self.cmd, tessdata)
        self.psm = psm
        self.timeout = timeout
        self.single_thread = False
        self.warnings: list[str] = []
        self.langs = self._list_langs()
        self.lang = self._pick_lang(lang)

    # -- tiện ích ---------------------------------------------------------
    def _argv(self, *args: str) -> list[str]:
        argv = [self.cmd]
        if self.tessdata:
            argv += ["--tessdata-dir", self.tessdata]
        return argv + list(args)

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        env = os.environ.copy()
        if self.single_thread:
            env["OMP_THREAD_LIMIT"] = "1"  # tránh nhiều tiến trình tranh nhau CPU
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            proc = subprocess.run(
                argv, capture_output=True, timeout=self.timeout, env=env, **kwargs
            )
        except subprocess.TimeoutExpired:
            raise OcrError(f"Tesseract chạy quá {self.timeout}s trên một trang.")
        except OSError as exc:
            raise OcrError(f"Không chạy được tesseract ({self.cmd}): {exc}")
        return (
            proc.returncode,
            proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"),
        )

    def version(self) -> str:
        _, out, err = self._run([self.cmd, "--version"])
        return (out or err).splitlines()[0] if (out or err) else "?"

    def _list_langs(self) -> list[str]:
        rc, out, err = self._run(self._argv("--list-langs"))
        langs = [
            line.strip()
            for line in (out + "\n" + err).splitlines()
            if line.strip() and _LANG_LINE.match(line.strip())
        ]
        if rc != 0 and not langs:
            raise OcrError(f"tesseract --list-langs lỗi: {(err or out).strip()}")
        if not langs:
            raise OcrError(
                f"Không thấy file *.traineddata nào trong tessdata ({self.tessdata or 'mặc định'})."
            )
        return langs

    def _pick_lang(self, lang: str) -> str:
        have = set(self.langs)
        where = self.tessdata or os.environ.get("TESSDATA_PREFIX") or "<thư mục tessdata>"
        if lang in ("", "auto"):
            if {"vie", "eng"} <= have:
                return "vie+eng"
            if "vie" in have:
                return "vie"
            if "eng" in have:
                self.warnings.append(
                    "Chưa có vie.traineddata nên đang OCR bằng 'eng': tiếng Việt sẽ mất hoặc sai dấu. "
                    f"Hãy chép vie.traineddata vào {where}"
                )
                return "eng"
            raise OcrError("tessdata không có ngôn ngữ nào dùng được.")
        missing = [part for part in lang.split("+") if part not in have]
        if missing:
            raise OcrError(
                f"Thiếu {', '.join(m + '.traineddata' for m in missing)} trong {where}. "
                f"Hiện có: {', '.join(sorted(have))}"
            )
        return lang

    def for_lang(self, lang: str) -> "Tesseract":
        clone = copy.copy(self)
        clone.warnings = []
        clone.lang = clone._pick_lang(lang)
        return clone

    # -- OCR một ảnh ------------------------------------------------------
    def image_to_page(self, png: str, number: int, width: int, height: int, dpi: int) -> Page:
        argv = self._argv(
            png, "stdout", "-l", self.lang, "--psm", str(self.psm), "--dpi", str(dpi), "tsv"
        )
        rc, out, err = self._run(argv)
        if rc != 0:
            raise OcrError(f"Tesseract lỗi ở trang {number}: {(err or out).strip()[:300]}")
        return Page(number, width, height, parse_tsv(out))


# --------------------------------------------------------------------------
# TSV -> Line
# --------------------------------------------------------------------------

# Ký tự có thể thò xuống dưới đường cơ sở. Hộp chữ của tesseract ôm sát glyph nên từ có
# các ký tự này cao hơn hẳn cùng cỡ chữ; bỏ chúng ra khi đo để cỡ chữ không bị nhiễu ~20%.
_DESCENDERS = set("gjpqyQJýỳỵỷỹ,;()[]{}/|_")


def _representative_height(words: list[tuple[str, int]]) -> float:
    """Cỡ chữ đại diện của dòng từ danh sách (từ, chiều cao hộp).

    Ưu tiên các từ không có chân chữ (đáy hộp = đường cơ sở); trong đó lấy phân vị 75%
    vì từ chỉ gồm chữ thấp (a, o, ơ…) có hộp thấp hơn từ có nét sổ lên (h, l, d…)."""
    alnum = [w for w in words if any(ch.isalnum() for ch in w[0])] or words
    flat = [h for text, h in alnum if not (set(text) & _DESCENDERS)] or [h for _, h in alnum]
    ordered = sorted(flat)
    return float(ordered[int(0.75 * (len(ordered) - 1) + 0.5)])


def parse_tsv(text: str) -> list[Line]:
    reader = csv.reader(io.StringIO(text.replace("\r\n", "\n")), delimiter="\t", quoting=csv.QUOTE_NONE)
    next(reader, None)  # dòng tiêu đề
    groups: dict[tuple[int, int, int], list[tuple[str, int, int, int, int, float]]] = {}
    for row in reader:
        if len(row) < 12 or row[0] != "5":  # level 5 = từ
            continue
        try:
            block, par, line = int(row[2]), int(row[3]), int(row[4])
            left, top, width, height = (int(row[i]) for i in (6, 7, 8, 9))
            conf = float(row[10])
        except ValueError:
            continue
        word = "\t".join(row[11:]).strip()
        if not word or conf < 0:
            continue
        groups.setdefault((block, par, line), []).append((word, left, top, width, height, conf))

    lines: list[Line] = []
    for (block, par, _), words in groups.items():  # dict giữ thứ tự xuất hiện = thứ tự đọc
        lines.append(
            Line(
                block=block,
                par=par,
                text=" ".join(w[0] for w in words),
                top=min(w[2] for w in words),
                bottom=max(w[2] + w[4] for w in words),
                left=min(w[1] for w in words),
                height=_representative_height([(w[0], w[4]) for w in words]),
                conf=statistics.fmean(w[5] for w in words),
                right=max(w[1] + w[3] for w in words),
                words=[(w[1], w[2], w[3], w[4], w[5]) for w in words],
            )
        )
    return lines


# --------------------------------------------------------------------------
# PDF -> Page
# --------------------------------------------------------------------------

def _import_pymupdf():
    try:
        import pymupdf  # type: ignore

        return pymupdf
    except ImportError:
        try:
            import fitz  # type: ignore

            return fitz
        except ImportError:
            raise OcrError("Thiếu PyMuPDF. Chạy: pip install pymupdf")


def parse_page_spec(spec: Optional[str], total: int) -> list[int]:
    """'1-3,5' -> [0,1,2,4] (chỉ số từ 0)."""
    if not spec or not spec.strip():
        return list(range(total))
    picked: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                start, end = int(a or 1), int(b or total)
            else:
                start = end = int(part)
        except ValueError:
            raise OcrError(f"Khoảng trang không hợp lệ: '{part}' (ví dụ đúng: 1-3,5)")
        if start < 1 or end < start or end > total:
            raise OcrError(f"Khoảng trang '{part}' nằm ngoài 1..{total}")
        picked.extend(range(start - 1, end))
    return sorted(set(picked))


def ocr_pdf(
    pdf_path: str,
    engine: Tesseract,
    *,
    dpi: int = 300,
    workers: int = 0,
    pages: Optional[str] = None,
    images_dir: Optional[str] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> list[Page]:
    """OCR từng trang. Nếu có images_dir thì đồng thời phát hiện hình và lưu PNG vào đó."""
    pymupdf = _import_pymupdf()
    np = detect = None
    if images_dir:
        try:
            import numpy as np  # noqa: F811
        except ImportError:
            raise OcrError("Tách hình cần numpy. Chạy: pip install numpy")
        from .figures import detect_figures as detect
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:
        raise OcrError(f"Không mở được PDF: {exc}")
    if doc.needs_pass:
        raise OcrError("PDF có mật khẩu, hãy gỡ mật khẩu trước.")

    indices = parse_page_spec(pages, len(doc))
    if not indices:
        raise OcrError("PDF không có trang nào.")
    workers = workers or max(1, min((os.cpu_count() or 2) - 1, 6))
    workers = min(workers, len(indices))
    engine.single_thread = workers > 1

    results: dict[int, Page] = {}
    pending: dict = {}
    done = 0

    def task(png: str, number: int, width: int, height: int, gray) -> Page:
        page = engine.image_to_page(png, number, width, height, dpi)
        if gray is not None:
            page.figures = detect(gray, page.lines, dpi)
        return page

    def save_figures(idx: int, page: Page) -> None:
        # Chạy ở luồng chính (PyMuPDF không thread-safe). Cắt từ bản render màu cùng DPI
        # thay vì dùng clip= để không bị lệch khi trang bị xoay.
        if not page.figures:
            return
        os.makedirs(images_dir, exist_ok=True)
        color = doc[idx].get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
        arr = np.frombuffer(color.samples, dtype=np.uint8).reshape(color.height, color.stride)
        arr = arr[:, : color.width * 3].reshape(color.height, color.width, 3)
        for k, fig in enumerate(page.figures, 1):
            sub = np.ascontiguousarray(arr[fig.top : fig.bottom, fig.left : fig.right])
            if sub.size == 0:
                continue
            name = f"p{idx + 1:03d}_fig{k:02d}.png"
            pymupdf.Pixmap(pymupdf.csRGB, sub.shape[1], sub.shape[0], sub.tobytes(), False).save(
                os.path.join(images_dir, name)
            )
            fig.file = name
        page.figures = [f for f in page.figures if f.file]

    def collect() -> None:
        nonlocal done
        finished, _ = wait(list(pending), return_when=FIRST_COMPLETED)
        for fut in finished:
            idx, png = pending.pop(fut)
            try:
                page = fut.result()
                if images_dir:
                    save_figures(idx, page)
                results[idx] = page
            finally:
                try:
                    os.unlink(png)
                except OSError:
                    pass
            done += 1
            if progress:
                progress(done, len(indices))

    with tempfile.TemporaryDirectory(prefix="ocr2md_") as tmp, ThreadPoolExecutor(workers) as pool:
        for idx in indices:
            if cancelled and cancelled():
                raise Cancelled()
            # Render trong luồng chính vì PyMuPDF không thread-safe; OCR mới chạy song song.
            pix = doc[idx].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
            png = os.path.join(tmp, f"p{idx + 1}.png")
            pix.save(png)
            gray = None
            if detect:
                gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)
                gray = gray[:, : pix.width].copy()
            fut = pool.submit(task, png, idx + 1, pix.width, pix.height, gray)
            pending[fut] = (idx, png)
            while len(pending) >= workers * 2:
                collect()
        while pending:
            if cancelled and cancelled():
                raise Cancelled()
            collect()

    return [results[i] for i in sorted(results)]


def ocr_image(
    image_path: str,
    engine: Tesseract,
    *,
    dpi: int = 300,
    pages: Optional[str] = None,
    images_dir: Optional[str] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> list[Page]:
    """OCR ảnh tĩnh hoặc từng frame của TIFF/GIF/WebP nhiều trang."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        source = Image.open(image_path)
    except (OSError, UnidentifiedImageError) as exc:
        raise OcrError(f"Không mở được ảnh: {exc}") from exc

    try:
        indices = parse_page_spec(pages, getattr(source, "n_frames", 1))
        if not indices:
            raise OcrError("Ảnh không có trang nào.")
        result = []
        with tempfile.TemporaryDirectory(prefix="ocr2md_image_") as tmp:
            for done, idx in enumerate(indices, 1):
                if cancelled and cancelled():
                    raise Cancelled()
                try:
                    source.seek(idx)
                    frame = ImageOps.exif_transpose(source.copy()).convert("RGBA")
                    canvas = Image.new("RGBA", frame.size, "white")
                    canvas.alpha_composite(frame)
                    color = canvas.convert("RGB")
                    png = os.path.join(tmp, f"p{idx + 1}.png")
                    color.save(png)
                    page = engine.image_to_page(png, idx + 1, color.width, color.height, dpi)
                    if images_dir:
                        import numpy as np
                        from .figures import detect_figures
                        gray = np.asarray(color.convert("L"))
                        page.figures = detect_figures(gray, page.lines, dpi)
                        if page.figures:
                            os.makedirs(images_dir, exist_ok=True)
                        for k, fig in enumerate(page.figures, 1):
                            name = f"p{idx + 1:03d}_fig{k:02d}.png"
                            color.crop((fig.left, fig.top, fig.right, fig.bottom)).save(
                                os.path.join(images_dir, name)
                            )
                            fig.file = name
                    result.append(page)
                except (OSError, ValueError, Image.DecompressionBombError) as exc:
                    raise OcrError(f"Không đọc được trang ảnh {idx + 1}: {exc}") from exc
                if progress:
                    progress(done, len(indices))
        return result
    finally:
        source.close()