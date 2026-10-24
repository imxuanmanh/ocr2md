import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ocr2md import ai, config
from ocr2md.ocr import Tesseract, find_tesseract, OcrError
from ocr2md.web import create_app


class ConfigFileTests(unittest.TestCase):
    def test_roundtrip_and_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "config.json"
            config.save(config.Settings(tesseract="C:\\T\\tesseract.exe", ai_api_key="sk-x"), path)
            loaded = config.load(path)
            self.assertEqual((loaded.tesseract, loaded.ai_api_key), ("C:\\T\\tesseract.exe", "sk-x"))
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_corrupt_file_is_set_aside_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(config.load(path), config.Settings())
            self.assertTrue((Path(d) / "config.json.bad").exists())

    def test_unknown_and_wrong_typed_fields_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text(json.dumps({"tesseract": "x", "evil": "y", "ai_model": 5}), encoding="utf-8")
            loaded = config.load(path)
            self.assertEqual((loaded.tesseract, loaded.ai_model), ("x", ""))


class TesseractPathTests(unittest.TestCase):
    def test_refuses_arbitrary_executable(self):
        with tempfile.TemporaryDirectory() as d:
            evil = Path(d) / "calc.exe"
            evil.write_text("x")
            with self.assertRaises(OcrError):
                find_tesseract(str(evil))


class WebSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"OCR2MD_CONFIG": str(Path(self.tmp.name) / "c.json")})
        self.env.start()
        self.app = create_app(None, engine_error="Không tìm thấy tesseract")
        self.c = self.app.test_client()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_starts_without_tesseract_and_blocks_jobs(self):
        cfg = self.c.get("/api/config").get_json()
        self.assertFalse(cfg["engine_ok"])
        self.assertEqual(cfg["lang_options"], ["auto"])
        import io
        r = self.c.post("/api/jobs", data={"file": (io.BytesIO(b"%PDF-1.4"), "a.pdf")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Tesseract", r.get_json()["error"])

    def test_bad_tesseract_path_rejected_and_not_saved(self):
        r = self.c.post("/api/settings", json={"tesseract": "/no/such/tesseract"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Path(os.environ["OCR2MD_CONFIG"]).exists())

    def test_save_ai_settings_without_tesseract_and_key_never_returned(self):
        r = self.c.post("/api/settings", json={"ai_provider": "custom", "ai_base_url": "http://localhost:1/v1", "ai_model": "m", "ai_api_key": "sk-secret"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("sk-secret", r.get_data(as_text=True))
        self.assertTrue(r.get_json()["ai_key_saved"])
        self.assertNotIn("sk-secret", self.c.get("/api/settings").get_data(as_text=True))
        self.assertIn("sk-secret", Path(os.environ["OCR2MD_CONFIG"]).read_text())  # nhưng có trên đĩa

    def test_changing_target_drops_saved_key(self):
        self.c.post("/api/settings", json={"ai_provider": "deepseek", "ai_api_key": "sk-secret"})
        r = self.c.post("/api/settings", json={"ai_provider": "custom", "ai_base_url": "http://evil.example/v1"})
        self.assertFalse(r.get_json()["ai_key_saved"])
        # đổi model thôi thì giữ key
        self.c.post("/api/settings", json={"ai_provider": "deepseek", "ai_api_key": "sk-2"})
        r = self.c.post("/api/settings", json={"ai_model": "other"})
        self.assertTrue(r.get_json()["ai_key_saved"])

    def test_validation(self):
        self.assertEqual(self.c.post("/api/settings", json={"ai_provider": "nope"}).status_code, 400)
        self.assertEqual(self.c.post("/api/settings", json={"ai_base_url": "file:///etc/passwd"}).status_code, 400)
        self.assertEqual(self.c.post("/api/settings", json={"tesseract": 5}).status_code, 400)

    def test_cross_site_and_rebinding_blocked(self):
        r = self.c.post("/api/settings", json={"ai_model": "x"}, headers={"Origin": "http://evil.example"})
        self.assertEqual(r.status_code, 403)
        r = self.c.get("/api/settings", headers={"Host": "evil.example:8765"})
        self.assertEqual(r.status_code, 403)
        r = self.c.post("/api/settings", json={"ai_model": "x"}, headers={"Origin": "http://localhost"})
        self.assertEqual(r.status_code, 200)  # cùng origin (test client dùng Host: localhost)

    def test_allowed_hosts_option(self):
        app = create_app(None, allowed_hosts=("my-box",))
        c = app.test_client()
        self.assertEqual(c.get("/api/config", headers={"Host": "my-box:8765"}).status_code, 200)
        self.assertEqual(c.get("/api/config", headers={"Host": "evil.example"}).status_code, 403)
        self.assertEqual(create_app(None, allowed_hosts=("*",)).test_client().get("/api/config", headers={"Host": "x.y"}).status_code, 200)

    def test_ai_key_from_config_beats_env_but_not_for_other_target(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            self.assertEqual(ai.AiConfig(api_key="saved").resolved()["key"], "saved")
            self.assertEqual(ai.AiConfig().resolved()["key"], "env-key")


class WebSettingsWithTesseractTests(unittest.TestCase):
    def test_valid_path_builds_engine(self):
        try:
            exe = find_tesseract()
        except OcrError:
            self.skipTest("không có tesseract")
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"OCR2MD_CONFIG": str(Path(d) / "c.json")}):
            c = create_app(None, engine_error="x").test_client()
            r = c.post("/api/settings", json={"tesseract": f'"{exe}"'})  # dán kèm dấu ngoặc kép
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            self.assertTrue(r.get_json()["engine"]["ok"])
            self.assertTrue(c.get("/api/config").get_json()["engine_ok"])


if __name__ == "__main__":
    unittest.main()
