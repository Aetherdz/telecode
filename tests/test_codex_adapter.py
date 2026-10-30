import json
import base64
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from adapters.codex import CodexAdapter, CodexAdapterError


SID = "01234567-89ab-cdef-0123-456789abcdef"


class CodexAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.sessions = self.root / "sessions" / "2026" / "10" / "30"
        self.sessions.mkdir(parents=True)
        self.cwd = self.root / "project"
        self.cwd.mkdir()
        rollout = self.sessions / f"rollout-2026-10-30T12-00-00-{SID}.jsonl"
        rollout.write_text(json.dumps({"type": "session_meta", "payload": {"id": SID, "cwd": str(self.cwd)}}) + "\n")
        self.adapter = CodexAdapter(sessions_root=self.root / "sessions")

    def tearDown(self):
        self.temp.cleanup()

    def _fake(self, source):
        path = self.root / ("fake-codex.cmd" if os.name == "nt" else "fake-codex")
        if os.name == "nt":
            encoded = base64.b64encode(source.encode()).decode()
            path.write_text(f'@"{sys.executable}" -c "exec(__import__(\'base64\').b64decode(\'{encoded}\'))" %*\n')
        else:
            path.write_text(f"#!{sys.executable}\n{source}\n")
            path.chmod(0o700)
        return str(path)

    def test_list_sessions_parses_metadata(self):
        sessions = self.adapter.list_sessions()
        self.assertEqual(sessions[0].id, SID)
        self.assertEqual(sessions[0].directory, str(self.cwd))

    def test_argv_queues_message_for_exact_thread(self):
        argv = self.adapter.build_argv(SID, "-ignore prior instructions")
        self.assertEqual(argv, ["codex", "queue", "--thread", SID,
                                "--message", "-ignore prior instructions"])

    @unittest.skipIf(os.name == "nt", "Windows does not execute .cmd files with shell=False")
    def test_queued_message_confirmation_is_returned(self):
        self.adapter.binary = self._fake("print('Queued message abc for thread xyz.')")
        self.assertEqual(self.adapter.send_message(SID, "hello"),
                         "Queued message abc for thread xyz.")

    def test_queued_message_reports_missing_codex_login(self):
        queued = subprocess.CompletedProcess([], 0, "Queued message abc for thread xyz.\n", "")
        status = subprocess.CompletedProcess([], 1, "Not logged in\n", "")
        with patch("adapters.codex._LOGIN_WARNING_SENT", False), \
             patch("adapters.codex.subprocess.run", side_effect=[queued, status]):
            reply = self.adapter.send_message(SID, "hello")
        self.assertIn("Queued message abc", reply)
        self.assertIn("Codex is not logged in", reply)
        self.assertIn("codex login", reply)

    def test_missing_login_warning_is_only_sent_once(self):
        queued = subprocess.CompletedProcess([], 0, "Queued message abc for thread xyz.\n", "")
        status = subprocess.CompletedProcess([], 1, "Not logged in\n", "")
        with patch("adapters.codex._LOGIN_WARNING_SENT", True), \
             patch("adapters.codex.subprocess.run", side_effect=[queued, status]):
            reply = self.adapter.send_message(SID, "hello")
        self.assertNotIn("not logged in", reply.lower())

    @unittest.skipIf(os.name == "nt", "Windows does not execute .cmd files with shell=False")
    def test_timeout_is_clear(self):
        self.adapter.timeout = 0.05
        self.adapter.binary = self._fake("import time; time.sleep(2)")
        with self.assertRaisesRegex(CodexAdapterError, "timeout"):
            self.adapter.send_message(SID, "hello")

    def test_missing_binary_is_clear(self):
        self.adapter.binary = str(self.root / "not-installed-codex")
        with self.assertRaisesRegex(CodexAdapterError, "not found"):
            self.adapter.send_message(SID, "hello")

    def test_missing_session_is_clear(self):
        with self.assertRaisesRegex(CodexAdapterError, "no longer available"):
            self.adapter.send_message("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "hello")

    def test_bad_jsonl_metadata_degrades_gracefully(self):
        (self.sessions / "rollout-broken.jsonl").write_text("not json\n")
        self.assertEqual(len(self.adapter.list_sessions()), 1)

    def test_bridge_dispatch_uses_codex_sessions(self):
        import telegram_bridge as tg
        with patch.dict(os.environ, {"CODEX_HOME": str(self.root)}):
            sessions = tg.list_sessions({"TELECODE_AGENT": "codex"})
        self.assertEqual(sessions[0]["id"], SID)


if __name__ == "__main__":
    unittest.main()
