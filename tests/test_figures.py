import unittest

import numpy as np

from ocr2md.figures import detect_figures
from ocr2md.markdown import build_markdown
from ocr2md.ocr import Figure, Line, Page


def line(text, top, left=100, h=20, words=None):
    ws = words if words is not None else [(left, top, 400, h, 95.0)]
    return Line(1, 1, text, top, top + h, left, h, 95, right=left + 400, words=ws)


class FigureTests(unittest.TestCase):
    def page(self):
        g = np.full((1400, 1000), 245, np.uint8)
        g[400:800, 150:850] = np.random.default_rng(0).integers(40, 200, (400, 700))  # "ảnh"
        return g

    def test_detects_photo_block_and_caption(self):
        cap = line("Hình 1: Mô tả", 830, left=150)
        figs = detect_figures(self.page(), [cap], 100)
        self.assertEqual(len(figs), 1)
        f = figs[0]
        self.assertLessEqual(f.left, 150 + 20)
        self.assertGreaterEqual(f.right, 850 - 20)
        self.assertEqual(f.alt, "Hình 1: Mô tả")

    def test_text_covered_block_is_not_a_figure(self):
        words = [(150 + i * 70, 420 + j * 30, 60, 22, 95.0) for i in range(10) for j in range(12)]
        self.assertEqual(detect_figures(self.page(), [line("x", 420, words=words)], 100), [])

    def test_blank_page_has_no_figures(self):
        self.assertEqual(detect_figures(np.full((1400, 1000), 250, np.uint8), [], 100), [])


class ImageMarkdownTests(unittest.TestCase):
    def test_image_is_inserted_between_paragraphs_in_reading_order(self):
        page = Page(1, 1000, 1400, [line("Trước hình.", 200), line("Sau hình.", 900)])
        page.figures = [Figure(100, 400, 800, 800, alt="Hình 1", file="p001_fig01.png")]
        self.assertEqual(
            build_markdown([page], image_prefix="my images"),
            "Trước hình.\n\n![Hình 1](my%20images/p001_fig01.png)\n\nSau hình.\n",
        )

    def test_text_inside_figure_is_dropped(self):
        page = Page(1, 1000, 1400, [line("Nhãn trục", 500, left=200), line("Thân bài.", 100)])
        page.figures = [Figure(100, 400, 800, 800, file="p001_fig01.png")]
        md = build_markdown([page])
        self.assertNotIn("Nhãn trục", md)
        self.assertIn("![Hình trang 1](images/p001_fig01.png)", md)


if __name__ == "__main__":
    unittest.main()
