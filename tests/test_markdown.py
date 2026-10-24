import unittest

from ocr2md.markdown import build_markdown
from ocr2md.ocr import Line, Page, parse_page_spec, OcrError
from ocr2md.ai import _check, chunk_markdown


def L(text, top, h=20, block=1, par=1):
    return Line(block=block, par=par, text=text, top=top, bottom=top + h, left=100, height=h, conf=90)


def P(n, lines):
    return Page(n, 1000, 1400, lines)


class MarkdownTests(unittest.TestCase):
    def test_heading_and_paragraph(self):
        page = P(1, [L("Tiêu đề lớn", 200, 40, block=1), L("Đây là đoạn", 300, block=2), L("văn thứ nhất.", 325, block=2)])
        self.assertEqual(build_markdown([page]), "# Tiêu đề lớn\n\nĐây là đoạn văn thứ nhất.\n")

    def test_heading_levels_follow_size(self):
        page = P(1, [
            L("Chương", 200, 50, block=1),
            L("Mục nhỏ", 300, 32, block=2),
            L("Nội dung dài hơn nhiều để làm thân bài chiếm số ký tự lớn nhất.", 400, block=3),
        ])
        md = build_markdown([page])
        self.assertTrue(md.startswith("# Chương\n\n## Mục nhỏ\n\n"))

    def test_running_header_and_page_numbers_removed(self):
        pages = [
            P(i, [L("Báo cáo 2026", 30), L(f"Nội dung trang {i}.", 400), L(str(i), 1350)])
            for i in range(1, 5)
        ]
        md = build_markdown(pages)
        self.assertNotIn("Báo cáo", md)
        self.assertEqual(md.count("Nội dung trang"), 4)
        self.assertNotIn("\n1\n", md)

    def test_two_page_documents_also_lose_running_header(self):
        pages = [P(i, [L("ACME Confidential", 30), L(f"Trang nội dung số {i}.", 400)]) for i in (1, 2)]
        self.assertNotIn("ACME", build_markdown(pages))

    def test_tall_bullet_list_is_not_a_heading(self):
        page = P(1, [L("Thân bài dài để làm cỡ chữ chuẩn của trang này.", 200), L("- táo", 300, 26), L("- chuối", 330, 26)])
        md = build_markdown([page])
        self.assertIn("- táo\n- chuối", md)
        self.assertNotIn("#", md)

    def test_bullets_and_continuation(self):
        page = P(1, [L("• Một", 300), L("• Hai", 330), L("tiếp tục", 360), L("• Ba", 390)])
        self.assertEqual(build_markdown([page]), "- Một\n- Hai tiếp tục\n- Ba\n")

    def test_merge_paragraph_across_pages(self):
        pages = [P(1, [L("câu chưa hết ở trang", 400)]), P(2, [L("tiếp theo.", 200)])]
        self.assertEqual(build_markdown(pages), "câu chưa hết ở trang tiếp theo.\n")

    def test_no_merge_after_sentence_end(self):
        pages = [P(1, [L("Câu đã xong.", 400)]), P(2, [L("viết thường nhưng là đoạn mới", 200)])]
        self.assertEqual(build_markdown(pages).count("\n\n"), 1)

    def test_hyphenation_depends_on_language(self):
        page = P(1, [L("inter-", 300), L("national law", 325)])
        self.assertEqual(build_markdown([page], dehyphenate=True), "international law\n")
        self.assertEqual(build_markdown([page], dehyphenate=False), "inter-national law\n")

    def test_page_markers(self):
        pages = [P(1, [L("Một.", 400)]), P(2, [L("Hai.", 400)])]
        self.assertEqual(
            build_markdown(pages, page_markers=True),
            "<!-- page 1 -->\n\nMột.\n\n<!-- page 2 -->\n\nHai.\n",
        )

    def test_escape_line_start(self):
        page = P(1, [L("# không phải heading", 300)])
        self.assertTrue(build_markdown([page]).startswith("\\#"))

    def test_nfc_and_spacing(self):
        decomposed = "Tiếng Việt ,xin chào"
        self.assertEqual(build_markdown([P(1, [L(decomposed, 300)])]), "Tiếng Việt,xin chào\n")


class HelperTests(unittest.TestCase):
    def test_page_spec(self):
        self.assertEqual(parse_page_spec("1-3,5", 10), [0, 1, 2, 4])
        self.assertEqual(parse_page_spec(None, 3), [0, 1, 2])
        with self.assertRaises(OcrError):
            parse_page_spec("2-99", 5)

    def test_ai_guard_rejects_changed_numbers(self):
        self.assertIsNone(_check("Tổng 1.200 đồng", "Tổng 1.200 đồng"))
        self.assertIsNotNone(_check("Tổng 1.200 đồng", "Tổng 1.700 đồng"))
        self.assertIsNotNone(_check("một đoạn khá dài " * 10, "ngắn"))

    def test_chunking_keeps_all_text(self):
        md = "\n\n".join(f"đoạn {i} " * 50 for i in range(30))
        chunks = chunk_markdown(md, 2000)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("\n\n".join(chunks), md.strip())


if __name__ == "__main__":
    unittest.main()
