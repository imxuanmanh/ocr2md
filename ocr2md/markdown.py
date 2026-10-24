"""Biên tập kết quả OCR thành Markdown bằng quy tắc (không cần AI).

Những gì làm được: bỏ header/footer lặp lại và số trang, gom dòng thành đoạn,
nối đoạn bị cắt ngang giữa hai trang, suy ra heading từ cỡ chữ, nhận diện danh sách,
chuẩn hoá Unicode (NFC) và khoảng trắng.
Những gì KHÔNG làm được: bảng biểu, chữ đậm/nghiêng, cột đôi, sửa lỗi nhận diện chữ.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from urllib.parse import quote
from dataclasses import dataclass, field

from .ocr import Line, Page

_PAGENUM = re.compile(
    r"^\W*(?:trang|page)?\s*\d{1,4}(?:\s*(?:/|of|trên)\s*\d{1,4})?\W*$", re.IGNORECASE
)
_TERMINAL = re.compile(r"[.!?…:;\"”’)\]]$")
_TRANSLATE = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "­": ""})

_BULLET = re.compile(r"^[•·●■▪◦○◆►▶‣⁃]\s*|^[-–—*]\s+")
_ORDERED = re.compile(r"^(\d{1,3})[.)]\s+")
_LETTER = re.compile(r"^([a-z])\)\s+")

HEADING_RATIO = 1.25  # chữ cao hơn thân bài bấy nhiêu lần mới coi là heading
HEADER_ZONE = 0.09  # 9% trên/dưới trang là vùng header/footer


@dataclass
class Block:
    kind: str  # "h" | "p" | "list" | "img"
    page: int
    text: str = ""
    height: float = 0.0
    top: float = 0.0  # vị trí dọc trên trang, dùng để chèn hình đúng chỗ
    level: int = 0
    items: list[str] = field(default_factory=list)
    end_page: int = 0

    def __post_init__(self) -> None:
        self.end_page = self.end_page or self.page


# --------------------------------------------------------------------------
# Làm sạch văn bản
# --------------------------------------------------------------------------

def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_TRANSLATE)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?)\]])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    return text


def _join(parts: list[str], dehyphenate: bool) -> str:
    out = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not out:
            out = part
        elif re.search(r"\w-$", out) and part[:1].islower():
            # Từ bị ngắt dòng bằng gạch nối. Tiếng Việt hầu như không ngắt từ kiểu này,
            # nên với tiếng Việt coi đó là từ ghép thật ("Bắc-Nam") và giữ nguyên gạch.
            out = out[:-1] + part if dehyphenate else out + part
        else:
            out += " " + part
    return clean_text(out)


def _escape_start(text: str) -> str:
    """Tránh đoạn văn thường bị Markdown hiểu nhầm thành heading/list/quote."""
    if re.match(r"^(#{1,6}\s|>|[-+*]\s)", text):
        return "\\" + text
    return re.sub(r"^(\d+)([.)]\s)", r"\1\\\2", text)


# --------------------------------------------------------------------------
# Bước 1: bỏ header/footer
# --------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", text.strip().lower()))


def _in_edge(page: Page, line: Line) -> bool:
    return line.top < page.height * HEADER_ZONE or line.bottom > page.height * (1 - HEADER_ZONE)


def strip_running_heads(pages: list[Page]) -> list[Page]:
    counts: Counter[str] = Counter()
    for page in pages:
        counts.update({_norm(ln.text) for ln in page.lines if _in_edge(page, ln)})
    # Dòng ở vùng mép trang lặp lại ở >=2 trang (và >=40% số trang) mới coi là header/footer.
    # PDF 1 trang thì không bao giờ có gì lặp, nên không bị ảnh hưởng.
    threshold = max(2, math.ceil(0.4 * len(pages)))
    repeated = {key for key, n in counts.items() if key and n >= threshold}

    cleaned = []
    for page in pages:
        keep = [
            ln
            for ln in page.lines
            if not (
                _in_edge(page, ln)
                and (_norm(ln.text) in repeated or _PAGENUM.match(ln.text.strip()))
            )
        ]
        cleaned.append(Page(page.number, page.width, page.height, keep, page.figures))
    return cleaned


def _inside(line: Line, fig) -> bool:
    cx = (line.left + (line.right or line.left)) / 2
    cy = (line.top + line.bottom) / 2
    return fig.left <= cx <= fig.right and fig.top <= cy <= fig.bottom


def drop_figure_text(pages: list[Page]) -> list[Page]:
    """Bỏ các dòng nằm trong vùng hình: nhãn trục biểu đồ, và nhất là rác mà tesseract
    'đọc' ra từ ảnh chụp. Nội dung đó đã nằm trong chính file ảnh."""
    out = []
    for page in pages:
        if not page.figures:
            out.append(page)
            continue
        keep = [ln for ln in page.lines if not any(_inside(ln, f) for f in page.figures)]
        out.append(Page(page.number, page.width, page.height, keep, page.figures))
    return out


# --------------------------------------------------------------------------
# Bước 2: cỡ chữ thân bài
# --------------------------------------------------------------------------

def body_height(pages: list[Page]) -> float:
    """Trung vị có trọng số theo số ký tự: cỡ chữ chiếm nhiều chữ nhất là thân bài."""
    samples = sorted((ln.height, len(ln.text)) for p in pages for ln in p.lines if ln.height > 0)
    if not samples:
        return 0.0
    half = sum(w for _, w in samples) / 2
    acc = 0
    for height, weight in samples:
        acc += weight
        if acc >= half:
            return height
    return samples[-1][0]


# --------------------------------------------------------------------------
# Bước 3: dòng -> đoạn -> block
# --------------------------------------------------------------------------

def _height_jump(a: Line, b: Line) -> bool:
    lo, hi = sorted((a.height, b.height))
    return lo > 0 and hi / lo > 1.35


def _groups(page: Page) -> list[list[Line]]:
    groups: list[list[Line]] = []
    current: list[Line] = []
    for ln in page.lines:
        split_by_figure = current and any(current[-1].bottom <= f.top + 5 and f.bottom - 5 <= ln.top for f in page.figures)
        if current and (
            split_by_figure
            or (ln.block, ln.par) != (current[-1].block, current[-1].par)
            or _height_jump(current[-1], ln)
        ):
            groups.append(current)
            current = []
        current.append(ln)
    if current:
        groups.append(current)
    return groups


def _marker(text: str):
    if m := _BULLET.match(text):
        return "- ", text[m.end():]
    if m := _ORDERED.match(text):
        return f"{m.group(1)}. ", text[m.end():]
    if m := _LETTER.match(text):
        return f"- {m.group(1)}) ", text[m.end():]
    return None


def _blocks_from_group(lines: list[Line], page_no: int, body: float, dehyphenate: bool) -> list[Block]:
    height = sorted(ln.height for ln in lines)[len(lines) // 2]
    text = _join([ln.text for ln in lines], dehyphenate)
    if not text:
        return []
    blocks = _classify_group(lines, page_no, body, dehyphenate, height, text)
    top = float(min(ln.top for ln in lines))
    for block in blocks:
        block.top = top
    return blocks


def _classify_group(
    lines: list[Line], page_no: int, body: float, dehyphenate: bool, height: float, text: str
) -> list[Block]:
    marks = [_marker(ln.text) for ln in lines]
    # Heading không chứa dòng bullet. (Số thứ tự kiểu "1. Giới thiệu" thì vẫn có thể là heading.)
    has_bullet = any(m and m[0].startswith("- ") for m in marks)
    if (
        body
        and height >= body * HEADING_RATIO
        and len(lines) <= 3
        and len(text) <= 160
        and not has_bullet
    ):
        return [Block("h", page_no, text=text, height=height)]

    hits = [i for i, m in enumerate(marks) if m]
    if hits and (hits[0] == 0 or len(hits) >= 2):
        blocks: list[Block] = []
        if hits[0] > 0:
            intro = _join([ln.text for ln in lines[: hits[0]]], dehyphenate)
            if intro:
                blocks.append(Block("p", page_no, text=intro))
        items: list[tuple[str, list[str]]] = []
        for i in range(hits[0], len(lines)):
            if marks[i]:
                items.append((marks[i][0], [marks[i][1]]))
            else:
                items[-1][1].append(lines[i].text)
        blocks.append(
            Block("list", page_no, items=[prefix + _join(parts, dehyphenate) for prefix, parts in items])
        )
        return blocks

    return [Block("p", page_no, text=text)]


def _assign_heading_levels(blocks: list[Block]) -> None:
    heights = sorted({b.height for b in blocks if b.kind == "h"}, reverse=True)
    levels: dict[float, int] = {}
    top, level = None, 0
    for h in heights:
        if top is None or h < top * 0.9:  # cỡ chữ lệch >10% so với đầu nhóm -> cấp mới
            level += 1
            top = h
        levels[h] = min(level, 6)
    for b in blocks:
        if b.kind == "h":
            b.level = levels[b.height]


def _merge_pages(blocks: list[Block], dehyphenate: bool) -> list[Block]:
    merged: list[Block] = []
    for block in blocks:
        prev = merged[-1] if merged else None
        if (
            prev
            and prev.kind == "p"
            and block.kind == "p"
            and block.page != prev.end_page
            and not _TERMINAL.search(prev.text)
            and block.text[:1].islower()
        ):
            prev.text = _join([prev.text, block.text], dehyphenate)
            prev.end_page = block.page
        else:
            merged.append(block)
    return merged


def _render(blocks: list[Block], page_markers: bool) -> str:
    out: list[str] = []
    marked = 0
    for b in blocks:
        if page_markers and b.page > marked:
            out.append(f"<!-- page {b.page} -->")
        marked = max(marked, b.end_page)
        if b.kind == "h":
            out.append("#" * b.level + " " + b.text)
        elif b.kind == "list":
            out.append("\n".join(b.items))
        elif b.kind == "img":
            out.append(b.text)
        else:
            out.append(_escape_start(b.text))
    return "\n\n".join(out) + "\n" if out else ""


def _image_block(page: Page, fig, image_prefix: str) -> Block:
    alt = re.sub(r"\s+", " ", fig.alt or f"Hình trang {page.number}").strip()
    alt = alt.replace("[", "(").replace("]", ")")
    path = quote(f"{image_prefix.rstrip('/')}/{fig.file}" if image_prefix else fig.file)
    return Block("img", page.number, text=f"![{alt}]({path})", top=float(fig.top))


def build_markdown(
    pages: list[Page],
    *,
    page_markers: bool = False,
    dehyphenate: bool = True,
    image_prefix: str = "images",
) -> str:
    """image_prefix: đường dẫn (tương đối với file .md) tới thư mục chứa ảnh đã tách."""
    pages = drop_figure_text(strip_running_heads(sorted(pages, key=lambda p: p.number)))
    body = body_height(pages)
    blocks: list[Block] = []
    for page in pages:
        page_blocks: list[Block] = []
        for group in _groups(page):
            page_blocks.extend(_blocks_from_group(group, page.number, body, dehyphenate))
        page_blocks.extend(_image_block(page, fig, image_prefix) for fig in page.figures)
        page_blocks.sort(key=lambda b: b.top)  # sort ổn định: cùng vị trí thì giữ thứ tự đọc
        blocks.extend(page_blocks)
    _assign_heading_levels(blocks)
    return _render(_merge_pages(blocks, dehyphenate), page_markers)
