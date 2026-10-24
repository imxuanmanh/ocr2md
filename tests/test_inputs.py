import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw, ImageFont

from ocr2md.inputs import detect_input
from ocr2md.ocr import OcrError, Tesseract, find_tesseract
from ocr2md.pipeline import convert_file
from ocr2md.web import create_app


def sample_image():
    image = Image.new("RGB", (900, 180), "white")
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 48) if os.name == "nt" else ImageFont.load_default()
    ImageDraw.Draw(image).text((40, 50), "HELLO WORLD 123", fill="black", font=font)
    return image


class InputTests(unittest.TestCase):
    def test_detect_supported_formats_by_content(self):
        with tempfile.TemporaryDirectory() as d:
            image = sample_image()
            for ext in ("png", "jpg", "tiff", "bmp", "webp", "gif"):
                path = Path(d) / ("sample." + ext)
                image.save(path)
                self.assertEqual(detect_input(path), "jpeg" if ext == "jpg" else ext)
            bad = Path(d) / "bad.png"
            bad.write_bytes(b"not an image")
            with self.assertRaises(OcrError):
                detect_input(bad)

    def test_converts_multiframe_tiff_when_tesseract_available(self):
        try:
            engine = Tesseract(lang="eng")
        except OcrError:
            self.skipTest("Tesseract chưa được tải")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sample.tiff"
            image = sample_image()
            image.save(path, save_all=True, append_images=[image])
            result = convert_file(str(path), engine, pages="2")
            self.assertEqual(result.pages, 1)
            self.assertIn("HELLO WORLD 123", result.markdown)

    def test_web_accepts_image_and_rejects_fake_image(self):
        import io
        try:
            engine = Tesseract(lang="eng")
        except OcrError:
            self.skipTest("Tesseract chưa được tải")
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"OCR2MD_CONFIG": str(Path(d) / "config.json"), "TEMP": d, "TMP": d}):
            app = create_app(engine)
            client = app.test_client()
            bad = client.post("/api/jobs", data={"file": (io.BytesIO(b"junk"), "fake.png")}, content_type="multipart/form-data")
            self.assertEqual(bad.status_code, 400)
            image = sample_image()
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            stream.seek(0)
            good = client.post("/api/jobs", data={"file": (stream, "sample.png")}, content_type="multipart/form-data")
            self.assertEqual(good.status_code, 200)
            job_id = good.get_json()["id"]
            for _ in range(50):
                status = client.get(f"/api/jobs/{job_id}").get_json()
                if status["status"] in ("done", "error"):
                    break
                time.sleep(0.1)
            self.assertEqual(status["status"], "done", status)
            self.assertIn("HELLO WORLD 123", client.get(f"/api/jobs/{job_id}/result").get_json()["markdown"])


if __name__ == "__main__":
    unittest.main()