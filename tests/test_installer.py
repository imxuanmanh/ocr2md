import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ocr2md import installer
from ocr2md.ocr import OcrError
from ocr2md.web import create_app


class DownloadTests(unittest.TestCase):
    def test_download_checks_sha256_and_reports_progress(self):
        payload = b"portable installer"
        digest = hashlib.sha256(payload).hexdigest()
        response = io.BytesIO(payload)
        response.headers = {"Content-Length": str(len(payload))}
        with tempfile.TemporaryDirectory() as d, mock.patch("urllib.request.urlopen", return_value=response):
            progress = []
            target = Path(d) / "installer.exe"
            installer._download("https://example.test/file.exe", target, digest, lambda *args: progress.append(args), "installer")
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(progress[-1], ("installer", len(payload), len(payload)))
        response = io.BytesIO(payload)
        response.headers = {"Content-Length": str(len(payload))}
        with tempfile.TemporaryDirectory() as d, mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(OcrError):
                installer._download("https://example.test/file.exe", Path(d) / "bad.exe", "0" * 64, lambda *_: None, "installer")


    @unittest.skipUnless(os.name == "nt", "Windows installer")
    def test_custom_link_gets_own_install_directory(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            previous = base / f"tesseract-{installer.VERSION}"
            (previous / "tessdata").mkdir(parents=True)
            (previous / "tesseract.exe").write_bytes(b"old")
            for lang in installer.MODELS:
                (previous / "tessdata" / f"{lang}.traineddata").write_bytes(b"old")

            def fake_download(url, path, digest, progress, stage):
                path.write_bytes(b"new")

            def fake_extract(source, folder):
                (folder / "tessdata" / "configs").mkdir(parents=True)
                (folder / "tesseract.exe").write_bytes(b"new")
                (folder / "tessdata" / "configs" / "tsv").write_text("tsv")

            with mock.patch.object(installer, "_download", side_effect=fake_download), mock.patch.object(
                installer, "_extract", side_effect=fake_extract
            ):
                exe, tessdata = installer.install(
                    base, lambda *_: None, url="https://example.test/custom.exe", sha256="a" * 64
                )
            self.assertIn("tesseract-custom-", exe)
            self.assertEqual(Path(exe).read_bytes(), b"new")
            self.assertEqual((previous / "tesseract.exe").read_bytes(), b"old")
            self.assertTrue(Path(tessdata, "vie.traineddata").is_file())
    def test_custom_download_requires_checksum(self):
        client = create_app(None).test_client()
        response = client.post("/api/tesseract/download", json={"url": "https://example.test/custom.exe"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(client.post("/api/tesseract/download", json=[]).status_code, 400)


if __name__ == "__main__":
    unittest.main()