"""Nhận diện định dạng đầu vào theo nội dung file."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .ocr import OcrError

IMAGE_FORMATS = {
    "PNG": ".png",
    "JPEG": ".jpg",
    "TIFF": ".tiff",
    "BMP": ".bmp",
    "WEBP": ".webp",
    "GIF": ".gif",
}


def detect_input(path: str | Path) -> str:
    source = Path(path)
    try:
        with source.open("rb") as fh:
            if fh.read(5) == b"%PDF-":
                return "pdf"
        with Image.open(source) as img:
            image_format = img.format
            img.verify()
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise OcrError(f"Không đọc được file đầu vào: {exc}") from exc
    if image_format not in IMAGE_FORMATS:
        raise OcrError("Chỉ hỗ trợ PDF, PNG, JPEG, TIFF, BMP, WebP và GIF.")
    return image_format.lower()