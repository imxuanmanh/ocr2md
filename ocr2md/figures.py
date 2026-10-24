"""Phát hiện vùng hình trên trang đã render (không dùng mô hình học máy).

Ý tưởng: lấy những chỗ có "mực" mà tesseract KHÔNG nhận ra là chữ, gộp các mảnh gần nhau
thành khối, rồi loại khối nào trông giống bảng hoặc đoạn văn (có nhiều chữ nằm trong đó).

Đây là heuristic. Hợp với ảnh chụp, biểu đồ, sơ đồ, chữ ký, logo lớn. Có thể sót hình rất
nhạt hoặc rất nhỏ, và đôi khi nhận nhầm bảng vẽ bằng đường kẻ thưa là hình.
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np

from .ocr import Figure, Line

CAPTION = re.compile(
    r"^\s*(hinh|bieu\s*do|so\s*do|anh|figure|fig\.?|chart|diagram|photo)\s*\d+", re.IGNORECASE
)


def _fold(text: str) -> str:
    """Bỏ dấu để khớp cả khi tesseract đọc thiếu dấu ('Hinh 1' thay vì 'Hình 1')."""
    text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in text if not unicodedata.combining(ch))
WORD_CONF = 40  # từ có độ tin cậy từ mức này mới coi là chữ thật (chữ "nhận" từ ảnh thường rất thấp)
MIN_WIDTH, MIN_HEIGHT = 0.12, 0.05  # kích thước tối thiểu của hình, theo tỉ lệ trang
MIN_FILL = 0.15  # tỉ lệ ô có mực trong khung, loại các mảnh rải rác
MAX_TEXT_COVERAGE = 0.10  # chữ chiếm quá 10% diện tích khung -> bảng/đoạn văn, không phải hình
MAX_WORDS = 40
DILATE = 3  # số ô dùng để dính các mảnh của cùng một hình


def _dilate(mask: np.ndarray, steps: int) -> np.ndarray:
    for _ in range(steps):
        out = mask.copy()
        out[1:] |= mask[:-1]
        out[:-1] |= mask[1:]
        out[:, 1:] |= mask[:, :-1]
        out[:, :-1] |= mask[:, 1:]
        mask = out
    return mask


def _components(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    """Các thành phần liên thông (8 hướng) -> (minx, miny, maxx, maxy, số ô). Dùng bytearray
    phẳng thay vì chỉ số numpy trong vòng lặp để nhanh hơn ~10 lần."""
    padded = np.pad(mask, 1)
    _, width = padded.shape
    cells = bytearray(padded.astype(np.uint8).ravel().tobytes())
    offsets = (-width - 1, -width, -width + 1, -1, 1, width - 1, width, width + 1)
    boxes = []
    for start in np.flatnonzero(padded.ravel()).tolist():
        if cells[start] != 1:
            continue
        cells[start] = 2
        stack, count = [start], 0
        miny = minx = 1 << 30
        maxy = maxx = -1
        while stack:
            p = stack.pop()
            count += 1
            y, x = divmod(p, width)
            miny, maxy = min(miny, y), max(maxy, y)
            minx, maxx = min(minx, x), max(maxx, x)
            for o in offsets:
                q = p + o
                if cells[q] == 1:
                    cells[q] = 2
                    stack.append(q)
        boxes.append((minx - 1, miny - 1, maxx - 1, maxy - 1, count))
    return boxes


def _caption(lines: list[Line], left: int, top: int, right: int, bottom: int, h: int, w: int) -> str:
    best, best_gap = "", None
    for ln in lines:
        if not CAPTION.match(_fold(ln.text)):
            continue
        if ln.top >= bottom - 5:
            gap = max(0, ln.top - bottom)
        elif ln.bottom <= top + 5:
            gap = max(0, top - ln.bottom)
        else:
            continue
        if gap > 0.07 * h or not (left - 0.05 * w <= ln.left <= right):
            continue
        if best_gap is None or gap < best_gap:
            best, best_gap = ln.text, gap
    return re.sub(r"[\[\]]", "", best)[:120]


def detect_figures(gray: np.ndarray, lines: list[Line], dpi: int) -> list[Figure]:
    h, w = gray.shape
    cell = max(4, round(dpi / 40))
    gh, gw = h // cell, w // cell
    if gh < 12 or gw < 12:
        return []

    g = gray[: gh * cell, : gw * cell]
    paper = float(np.percentile(g[::3, ::3], 85))  # độ sáng nền giấy (bản scan thường không trắng tinh)
    dark = g < max(60.0, paper - 40)
    ink = dark.reshape(gh, cell, gw, cell).sum(axis=(1, 3)) >= max(2, int(cell * cell * 0.08))

    words = [wd for ln in lines for wd in ln.words if wd[4] >= WORD_CONF]
    for left, top, ww, hh, _ in words:  # xoá chữ thật khỏi bản đồ "mực"
        ink[max(0, top // cell - 1) : min(gh, (top + hh) // cell + 2),
            max(0, left // cell - 1) : min(gw, (left + ww) // cell + 2)] = False

    margin = max(1, round(0.015 * min(gh, gw)))  # bóng đen ở mép trang scan
    ink[:margin] = ink[-margin:] = False
    ink[:, :margin] = ink[:, -margin:] = False

    figures: list[Figure] = []
    for minx, miny, maxx, maxy, count in _components(_dilate(ink, DILATE)):
        bw, bh = maxx - minx + 1, maxy - miny + 1
        if bw < MIN_WIDTH * gw or bh < MIN_HEIGHT * gh or count / (bw * bh) < MIN_FILL:
            continue
        left, top = minx * cell, miny * cell
        right, bottom = min(w, (maxx + 1) * cell), min(h, (maxy + 1) * cell)

        inside = [
            wd for wd in words
            if left <= wd[0] + wd[2] / 2 <= right and top <= wd[1] + wd[3] / 2 <= bottom
        ]
        coverage = sum(wd[2] * wd[3] for wd in inside) / max(1, (right - left) * (bottom - top))
        if coverage > MAX_TEXT_COVERAGE or len(inside) > MAX_WORDS:
            continue
        figures.append(Figure(left, top, right, bottom, alt=_caption(lines, left, top, right, bottom, h, w)))

    return sorted(figures, key=lambda f: (f.top, f.left))
