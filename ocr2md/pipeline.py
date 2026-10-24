"""Quy trình dùng chung cho CLI và web: PDF/ảnh -> OCR -> Markdown (-> AI)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from . import ai
from .markdown import build_markdown
from .inputs import detect_input
from .ocr import Tesseract, ocr_image, ocr_pdf

# progress(stage, done, total) với stage in {"ocr", "format", "ai"}
ProgressFn = Callable[[str, int, int], None]


@dataclass
class ConvertResult:
    markdown: str
    markdown_ai: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    pages: int = 0
    lang: str = ""
    images: int = 0


def convert_file(
    input_path: str,
    engine: Tesseract,
    *,
    dpi: int = 300,
    workers: int = 0,
    pages: Optional[str] = None,
    page_markers: bool = False,
    images_dir: Optional[str] = None,
    image_prefix: str = "images",
    use_ai: bool = False,
    ai_config: Optional[ai.AiConfig] = None,
    progress: Optional[ProgressFn] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> ConvertResult:
    notify = progress or (lambda *_: None)
    warnings = list(engine.warnings)

    source_type = detect_input(input_path)
    convert = ocr_pdf if source_type == "pdf" else ocr_image
    options = dict(
        dpi=dpi,
        pages=pages,
        images_dir=images_dir,
        progress=lambda done, total: notify("ocr", done, total),
        cancelled=cancelled,
    )
    if source_type == "pdf":
        options["workers"] = workers
    ocr_pages = convert(input_path, engine, **options)

    notify("format", 0, 1)
    markdown = build_markdown(
        ocr_pages,
        page_markers=page_markers,
        dehyphenate="vie" not in engine.lang.split("+"),
        image_prefix=image_prefix,
    )
    notify("format", 1, 1)

    result = ConvertResult(
        markdown=markdown,
        warnings=warnings,
        pages=len(ocr_pages),
        lang=engine.lang,
        images=sum(len(p.figures) for p in ocr_pages),
    )
    if not markdown.strip():
        warnings.append("Không nhận diện được chữ nào. Thử tăng DPI hoặc kiểm tra ngôn ngữ OCR.")
        return result

    if use_ai:
        refined = ai.refine(
            markdown,
            config=ai_config,
            progress=lambda done, total: notify("ai", done, total),
            cancelled=cancelled,
        )
        result.markdown_ai = refined.text
        warnings.extend(refined.warnings)
    return result
