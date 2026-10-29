import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "get_telegram_id.py"
spec = importlib.util.spec_from_file_location("get_telegram_id", SCRIPT)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class GetTelegramIdTests(unittest.TestCase):
    def test_configure_saves_id_and_returns_after_first_private_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            envfile = pathlib.Path(tmp) / "telegram.env"
            envfile.write_text("TG_BOT_TOKEN=12345:" + "a" * 25 + "\nTG_CHAT_ID=\n")
            update = {"update_id": 100, "message": {
                "chat": {"type": "private", "id": 7654321},
                "from": {"id": 7654321},
            }}

            class Response:
                def __init__(self, payload): self.payload = payload
                def __enter__(self): return self
                def __exit__(self, *_): return False
                def read(self): return self.payload

            def urlopen(request, timeout=0):
                if "getUpdates" in request.full_url:
                    return Response(b'{"ok":true,"result":[' + __import__("json").dumps(update).encode() + b']}')
                return Response(b'{"ok":true,"result":{}}')

            with patch.dict("os.environ", {"TELEGRAM_BRIDGE_HOME": tmp}), \
                 patch.object(helper.sys, "argv", [str(SCRIPT), "--configure", "--timeout", "2"]), \
                 patch.object(helper.urllib.request, "urlopen", side_effect=urlopen), \
                 patch("builtins.print"):
                self.assertEqual(helper.main(), 0)
            self.assertIn("TG_CHAT_ID=7654321", envfile.read_text())


if __name__ == "__main__":
    unittest.main()
