import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import telegram_bridge as tg


class TelegramApiLocalTests(unittest.TestCase):
    def test_api_uses_local_fake_server_and_dummy_token(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                size = int(self.headers.get("Content-Length", "0"))
                requests.append((self.path, self.rfile.read(size).decode()))
                body = json.dumps({"ok": True, "result": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with patch.dict(os.environ, {"TELECODE_TELEGRAM_API_BASE": base}):
                result = tg.api("12345:FAKE_TOKEN_NOT_VALID", "sendMessage", {"chat_id": "1", "text": "test"})
            self.assertTrue(result["ok"])
            self.assertEqual(requests[0][0], "/bot12345:FAKE_TOKEN_NOT_VALID/sendMessage")
            self.assertIn("text=test", requests[0][1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
