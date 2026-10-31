import os
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
    @unittest.skipUnless(os.name == "posix", "POSIX mode bits are not portable")
    def test_write_private_sets_exact_mode_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "telegram.env"
            helper._write_private(path, ["TG_BOT_TOKEN=secret", "TG_CHAT_ID=1"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_write_private_chmod_failure_preserves_original_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "telegram.env"
            path.write_text("original\n")
            before = set(path.parent.iterdir())
            if not hasattr(os, "fchmod"):
                self.skipTest("fchmod failure injection is unavailable on this platform")
            with patch.object(helper.os, "fchmod", side_effect=OSError("chmod failed")):
                with self.assertRaisesRegex(OSError, "chmod failed"):
                    helper._write_private(path, ["replacement"])
            self.assertEqual(path.read_text(), "original\n")
            self.assertEqual(set(path.parent.iterdir()), before)

    def test_write_private_replace_failure_preserves_original_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "telegram.env"
            path.write_text("original\n")
            before = set(path.parent.iterdir())
            with patch.object(helper.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    helper._write_private(path, ["replacement"])
            self.assertEqual(path.read_text(), "original\n")
            self.assertEqual(set(path.parent.iterdir()), before)

    def test_write_private_replace_failure_does_not_close_descriptor_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "telegram.env"
            real_fdopen = helper.os.fdopen
            opened = []
            class TrackingStream:
                def __init__(self, stream): self.stream = stream
                def __enter__(self): return self
                def __exit__(self, *args): return self.stream.__exit__(*args)
                def write(self, *args): return self.stream.write(*args)
                def flush(self): return self.stream.flush()
                def fileno(self): return self.stream.fileno()
                @property
                def closed(self): return self.stream.closed
            def tracking_fdopen(fd, *args, **kwargs):
                stream = TrackingStream(real_fdopen(fd, *args, **kwargs))
                opened.append(stream)
                return stream
            with patch.object(helper.os, "fdopen", side_effect=tracking_fdopen), \
                 patch.object(helper.os, "replace", side_effect=OSError("replace failed")), \
                 patch.object(helper.os, "close", wraps=helper.os.close) as close:
                with self.assertRaisesRegex(OSError, "replace failed"):
                    helper._write_private(path, ["replacement"])
            self.assertEqual(len(opened), 1)
            self.assertTrue(opened[0].closed)
            close.assert_not_called()
            self.assertFalse(list(path.parent.glob(".telegram.env.*")))

    def test_write_private_interrupt_closes_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "telegram.env"
            path.write_text("original\n")
            before = set(path.parent.iterdir())
            with patch.object(helper.os, "fsync", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    helper._write_private(path, ["replacement"])
            self.assertEqual(path.read_text(), "original\n")
            self.assertEqual(set(path.parent.iterdir()), before)

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

    def test_configure_uses_parsed_flag_not_global_argv(self):
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
                    import json
                    return Response(b'{"ok":true,"result":[' + json.dumps(update).encode() + b']}')
                return Response(b'{"ok":true,"result":{}}')

            with patch.dict("os.environ", {"TELEGRAM_BRIDGE_HOME": tmp}), \
                 patch.object(helper.sys, "argv", [str(SCRIPT), "--timeout", "2"]), \
                 patch.object(helper.urllib.request, "urlopen", side_effect=urlopen), \
                 patch("builtins.print"):
                self.assertEqual(helper.main(), 0)
            self.assertNotIn("TG_CHAT_ID=7654321", envfile.read_text())

    def test_http_error_is_reported_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            envfile = pathlib.Path(tmp) / "telegram.env"
            envfile.write_text("TG_BOT_TOKEN=12345:" + "a" * 25 + "\nTG_CHAT_ID=\n")
            error = helper.urllib.error.HTTPError("https://api.telegram.org", 401, "Unauthorized", {}, None)
            with patch.dict("os.environ", {"TELEGRAM_BRIDGE_HOME": tmp}), \
                 patch.object(helper.sys, "argv", [str(SCRIPT), "--timeout", "2"]), \
                 patch.object(helper.urllib.request, "urlopen", side_effect=error), \
                 patch("builtins.print"):
                with self.assertRaisesRegex(SystemExit, "Could not contact Telegram"):
                    helper.main()


if __name__ == "__main__":
    unittest.main()
