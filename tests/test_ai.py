import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from ocr2md import ai


class FakeOpenAI(BaseHTTPRequestHandler):
    requests: list = []
    hits_429 = 0

    def log_message(self, *a):
        pass

    def _reply(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOpenAI.requests.append((self.path, dict(self.headers), body))
        user = body["messages"][1]["content"]
        text = user.split("<ocr_markdown>\n", 1)[1].rsplit("\n</ocr_markdown>", 1)[0]
        finish = "stop"
        if "UNAUTHORIZED" in text:
            return self._reply(401, {"error": {"message": "bad key"}})
        if "RATELIMIT" in text and FakeOpenAI.hits_429 < 2:
            FakeOpenAI.hits_429 += 1
            return self._reply(429, {"error": {"message": "slow down"}})
        out = text
        if "teh" in text:
            out = text.replace("teh", "the")
        if "CHANGENUM" in text:
            out = text.replace("100", "700")
        if "DROPIMG" in text:
            out = text.replace("images/p001_fig01.png", "pics/p001_fig01.png")
        if "TRUNC" in text:
            finish = "length"
        if "FENCE" in text:
            out = "```markdown\n" + out + "\n```"
        self._reply(200, {"choices": [{"message": {"content": out}, "finish_reason": finish}]})


class AiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeOpenAI)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/v1"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeOpenAI.requests.clear()
        FakeOpenAI.hits_429 = 0
        self.env = mock.patch.dict(os.environ, {"FAKE_KEY": "secret-123"})
        self.env.start()
        self.sleep = mock.patch("time.sleep")
        self.sleep.start()
        self.split = mock.patch.object(ai, "chunk_markdown", lambda md: md.split("\n\n"))
        self.split.start()
        self.cfg = ai.AiConfig("custom", "m1", self.url, "FAKE_KEY")

    def tearDown(self):
        mock.patch.stopall()

    def test_fix_is_accepted_and_request_shape(self):
        res = ai.refine("Bao cao teh year", config=self.cfg)
        self.assertEqual(res.text, "Bao cao the year\n")
        self.assertEqual(res.accepted, 1)
        path, headers, body = FakeOpenAI.requests[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer secret-123")
        self.assertEqual(body["model"], "m1")
        self.assertEqual(body["temperature"], 0)
        self.assertNotIn("thinking", body)  # chỉ preset deepseek mới tắt thinking

    def test_guards_keep_original(self):
        for marker, expect in [
            ("CHANGENUM Tong 100 dong", "số"),
            ("DROPIMG " + "một đoạn văn khá dài để tỉ lệ độ dài không đổi nhiều. " * 3 + "![a](images/p001_fig01.png)", "link ảnh"),
            ("TRUNC van ban", "cắt cụt"),
        ]:
            res = ai.refine(marker, config=self.cfg)
            self.assertEqual(res.text, marker + "\n", marker)
            self.assertEqual(res.accepted, 0)
            self.assertIn(expect, res.warnings[0])

    def test_code_fence_is_unwrapped(self):
        self.assertEqual(ai.refine("FENCE teh", config=self.cfg).text, "FENCE the\n")

    def test_retries_on_429_then_succeeds(self):
        res = ai.refine("RATELIMIT teh", config=self.cfg)
        self.assertEqual(res.text, "RATELIMIT the\n")
        self.assertEqual(len(FakeOpenAI.requests), 3)

    def test_auth_failure_is_fatal_and_stops_early(self):
        with self.assertRaises(ai.AiError) as ctx:
            ai.refine("UNAUTHORIZED a\n\nb\n\nc", config=self.cfg)
        self.assertIn("401", str(ctx.exception))
        self.assertEqual(len(FakeOpenAI.requests), 1)

    def test_progress_and_multiple_chunks(self):
        seen = []
        res = ai.refine("teh a\n\nteh b", config=self.cfg, progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(res.text, "the a\n\nthe b\n")
        self.assertEqual(seen, [(1, 2), (2, 2)])


class ConfigTests(unittest.TestCase):
    def test_deepseek_defaults(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "k"}, clear=True):
            r = ai.AiConfig().resolved()
        self.assertEqual((r["provider"], r["model"], r["base_url"]), ("deepseek", "deepseek-flash", "https://api.deepseek.com"))
        self.assertEqual(r["extra"], {"thinking": {"type": "disabled"}})
        self.assertFalse(r["local"])

    def test_missing_key_and_model(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIn("DEEPSEEK_API_KEY", ai.check(ai.AiConfig())[1])
            self.assertIn("--ai-model", ai.check(ai.AiConfig("ollama"))[1])
            self.assertIn("--ai-base-url", ai.check(ai.AiConfig("custom", "m"))[1])
            self.assertTrue(ai.check(ai.AiConfig("ollama", "qwen"))[0])  # local: không cần key

    def test_ollama_is_reported_local(self):
        self.assertIn("không rời máy", ai.describe(ai.AiConfig("ollama", "qwen")))
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "k"}):
            self.assertIn("api.deepseek.com", ai.describe(ai.AiConfig()))


if __name__ == "__main__":
    unittest.main()
