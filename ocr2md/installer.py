"""Tải và cài Tesseract theo yêu cầu, không mang engine trong gói ứng dụng."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .ocr import OcrError

VERSION = "5.5.3"
INSTALLER_URL = (
    "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/"
    "tesseract-ocr-w64-setup-5.5.3.20260724.exe"
)
INSTALLER_SHA256 = "bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4"
MODELS = {
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    "vie": "79df64caf7bcfb2a27df5042ecb6121e196eada34da774956995747636d5bfa1",
    "osd": "9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff",
}
Progress = Callable[[str, int, int], None]


def _download(url: str, path: Path, expected_sha: str, progress: Progress, stage: str) -> None:
    if urlsplit(url).scheme != "https":
        raise OcrError("Link tải phải dùng HTTPS.")
    digest = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": f"ocr2md/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response, path.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                progress(stage, done, total)
    except (OSError, ValueError) as exc:
        raise OcrError(f"Không tải được {stage}: {exc}") from exc
    if digest.hexdigest() != expected_sha.lower():
        raise OcrError(f"SHA-256 của {stage} không khớp. File tải xuống đã bị loại bỏ.")


def _extract(installer: Path, folder: Path) -> None:
    seven_zip = Path(__file__).resolve().parent / "vendor" / "7zip" / "7z.exe"
    if not seven_zip.is_file():
        raise OcrError("Gói ứng dụng thiếu công cụ giải nén 7-Zip.")
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        proc = subprocess.run(
            [str(seven_zip), "x", str(installer), f"-o{folder}", "-y"],
            capture_output=True, text=True, timeout=180, **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OcrError(f"Không giải nén được Tesseract: {exc}") from exc
    if proc.returncode != 0:
        raise OcrError(f"Không giải nén được Tesseract: {(proc.stderr or proc.stdout)[-300:]}")


def install(
    base: Path,
    progress: Progress,
    *,
    url: str = INSTALLER_URL,
    sha256: str = INSTALLER_SHA256,
) -> tuple[str, str]:
    """Cài trong thư mục dữ liệu người dùng; trả về (exe, tessdata)."""
    if os.name != "nt":
        raise OcrError("Tải tự động hiện hỗ trợ Windows x64. Trên hệ khác hãy cài Tesseract bằng hệ điều hành.")
    if urlsplit(url).scheme != "https":
        raise OcrError("Link tải phải dùng HTTPS.")
    if len(sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in sha256):
        raise OcrError("SHA-256 phải có đúng 64 ký tự hex.")
    base.mkdir(parents=True, exist_ok=True)
    # Bản tự chọn có thư mục riêng, tránh âm thầm dùng lại bản mặc định đã tải.
    default = url == INSTALLER_URL and sha256.lower() == INSTALLER_SHA256
    name = f"tesseract-{VERSION}" if default else f"tesseract-custom-{sha256[:12].lower()}"
    target = base / name
    exe = target / "tesseract.exe"
    tessdata = target / "tessdata"
    if exe.is_file() and all((tessdata / f"{lang}.traineddata").is_file() for lang in MODELS):
        progress("complete", 1, 1)
        return str(exe), str(tessdata)
    if target.exists():
        raise OcrError(f"Bản cài Tesseract chưa hoàn chỉnh tại {target}. Hãy đổi tên hoặc xoá thư mục này rồi thử lại.")

    with tempfile.TemporaryDirectory(prefix="ocr2md_download_", dir=base) as tmp:
        temp = Path(tmp)
        installer = temp / "tesseract-installer.exe"
        _download(url, installer, sha256, progress, "installer")
        extracted = temp / "extracted"
        progress("extract", 0, 0)
        _extract(installer, extracted)
        if not (extracted / "tesseract.exe").is_file():
            raise OcrError("Gói tải về không chứa tesseract.exe.")

        staged = temp / "staged"
        staged.mkdir()
        shutil.copy2(extracted / "tesseract.exe", staged / "tesseract.exe")
        license_file = extracted / "doc" / "LICENSE"
        if license_file.is_file():
            shutil.copy2(license_file, staged / "LICENSE")
        for dll in extracted.glob("*.dll"):
            shutil.copy2(dll, staged / dll.name)
        (staged / "tessdata" / "configs").mkdir(parents=True)
        shutil.copy2(extracted / "tessdata" / "configs" / "tsv", staged / "tessdata" / "configs" / "tsv")
        for lang, digest in MODELS.items():
            _download(
                f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/{lang}.traineddata",
                staged / "tessdata" / f"{lang}.traineddata",
                digest, progress, lang,
            )
        os.replace(staged, target)
    progress("complete", 1, 1)
    return str(exe), str(tessdata)