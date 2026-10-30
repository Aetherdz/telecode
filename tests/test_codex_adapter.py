import json
import base64
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from adapters.base import AgentSession
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
        with patch.object(self.adapter, "_app_server_batch", return_value=[{"data": [], "nextCursor": None}]):
            sessions = self.adapter.list_sessions()
        self.assertEqual(sessions[0].id, SID)
        self.assertEqual(sessions[0].directory, str(self.cwd))

    def test_session_listing_merges_app_server_threads_from_other_workspaces(self):
        other_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        other_cwd = self.root / "outside-home-project"
        other_cwd.mkdir()
        with patch.object(self.adapter, "_app_server_batch", return_value=[{"data": [
                {"id": SID, "cwd": str(other_cwd), "name": "Renamed local thread", "updatedAt": 200},
                {"id": other_id, "cwd": str(other_cwd), "name": "Other project thread", "updatedAt": 300},
            ], "nextCursor": None}]):
            sessions = self.adapter.list_sessions()
        by_id = {session.id: session for session in sessions}
        self.assertEqual(set(by_id), {SID, other_id})
        self.assertEqual(by_id[SID].directory, str(other_cwd))
        self.assertEqual(by_id[SID].title, "Renamed local thread")

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
        with patch.object(self.adapter, "_app_server_batch", return_value=[{"data": [], "nextCursor": None}]):
            self.assertEqual(len(self.adapter.list_sessions()), 1)

    def test_create_session_verifies_persistence_via_thread_read(self):
        calls = []

        def fake_app_server_batch(calls_spec, timeout=45, patient=False):
            calls.extend(method for method, _ in calls_spec)
            return [{"thread": {"id": SID, "updatedAt": 100}}, {}, {}]

        with patch.object(self.adapter, "_app_server_batch", side_effect=fake_app_server_batch):
            session = self.adapter.create_session("My session")
        self.assertEqual(session.id, SID)
        self.assertEqual(session.title, "My session")
        self.assertEqual(calls, ["thread/start", "thread/name/set", "thread/resume"])

    def test_create_session_fails_when_thread_is_not_persisted(self):
        def fake_app_server_batch(calls_spec, timeout=45, patient=False):
            raise CodexAdapterError("no rollout found")

        with patch.object(self.adapter, "_app_server_batch", side_effect=fake_app_server_batch):
            with self.assertRaisesRegex(CodexAdapterError, "did not persist") as caught:
                self.adapter.create_session("My session")
            self.assertNotIn("no rollout found", str(caught.exception))

    def test_create_session_requires_ephemeral_false(self):
        captured = {}

        def fake_app_server_batch(calls_spec, timeout=45, patient=False):
            captured["params"] = calls_spec[0][1]
            return [{"thread": {"id": SID, "updatedAt": 100}}, {}, {}]

        with patch.object(self.adapter, "_app_server_batch", side_effect=fake_app_server_batch):
            self.adapter.create_session("My session")
        self.assertIs(captured["params"]["ephemeral"], False)

    def test_create_session_names_thread_from_first_result(self):
        captured = {}

        def fake_app_server_batch(calls_spec, timeout=45, patient=False):
            start = {"thread": {"id": SID, "updatedAt": 100}}
            captured["name_params"] = calls_spec[1][1]([start])
            captured["resume_params"] = calls_spec[2][1]([start])
            return [start, {}, {}]

        with patch.object(self.adapter, "_app_server_batch", side_effect=fake_app_server_batch):
            self.adapter.create_session("My session")
        self.assertEqual(captured["name_params"],
                         {"threadId": SID, "name": "My session"})
        self.assertEqual(captured["resume_params"],
                         {"threadId": SID, "approvalPolicy": "never", "sandbox": "read-only"})

    def test_list_sessions_batches_all_pages_into_one_process(self):
        spawn_log = self.root / "spawns"
        other_id = "b1b2b3b4-bbbb-cccc-dddd-eeeeeeeeeeee"
        source = (
            "import sys, json\n"
            f"open({str(spawn_log)!r}, 'a').write('x')\n"
            "for line in sys.stdin:\n"
            "    m = json.loads(line)\n"
            "    if m.get('method') == 'initialize':\n"
            "        reply = {'id': m['id'], 'result': {}}\n"
            "    elif m.get('method') == 'thread/list':\n"
            "        if (m.get('params') or {}).get('cursor') == 'c1':\n"
            f"            data = [{{'id': {other_id!r}, 'cwd': {str(self.cwd)!r}, 'name': 'p2', 'updatedAt': 200}}]\n"
            "            reply = {'id': m['id'], 'result': {'data': data, 'nextCursor': None}}\n"
            "        else:\n"
            f"            data = [{{'id': {SID!r}, 'cwd': {str(self.cwd)!r}, 'name': 'p1', 'updatedAt': 100}}]\n"
            "            reply = {'id': m['id'], 'result': {'data': data, 'nextCursor': 'c1'}}\n"
            "    else:\n"
            "        continue\n"
            "    sys.stdout.write(json.dumps(reply) + '\\n')\n"
            "    sys.stdout.flush()\n"
        )
        self.adapter.binary = self._fake(source)
        sessions = self.adapter.list_sessions()
        by_id = {session.id: session for session in sessions}
        self.assertEqual(set(by_id), {SID, other_id})
        self.assertEqual(spawn_log.read_text(), "x", "app-server must spawn exactly once")

    def test_validate_session_uses_thread_read_without_full_listing(self):
        with patch.object(self.adapter, "_app_server", return_value={"thread": {
                "id": SID, "cwd": str(self.cwd), "name": "Named", "updatedAt": 500}}) as read, \
             patch.object(self.adapter, "list_sessions") as listing:
            session = self.adapter.validate_session(SID)
        self.assertEqual(session.id, SID)
        self.assertEqual(session.title, "Named")
        self.assertEqual(session.updated, 500)
        listing.assert_not_called()

    def test_validate_session_falls_back_to_listing_when_thread_read_fails(self):
        with patch.object(self.adapter, "_app_server",
                          side_effect=CodexAdapterError("thread not loaded")), \
             patch.object(self.adapter, "list_sessions",
                          return_value=[AgentSession(SID, "from list", str(self.cwd), "codex", 42)]):
            session = self.adapter.validate_session(SID)
        self.assertEqual(session.id, SID)
        self.assertEqual(session.updated, 42)

    def test_validate_session_returns_none_for_unknown_thread(self):
        with patch.object(self.adapter, "_app_server",
                          side_effect=CodexAdapterError("thread not loaded")), \
             patch.object(self.adapter, "list_sessions", return_value=[]):
            self.assertIsNone(self.adapter.validate_session(SID))

    def test_list_models_batches_pages_into_one_process(self):
        payloads = iter([[{"data": [{"id": "m1", "modelProvider": "openai", "displayName": "M One"}],
                           "nextCursor": "c2"},
                          {"data": [{"id": "m2", "modelProvider": "openai"}], "nextCursor": None}]])
        with patch.object(self.adapter, "_app_server_batch", side_effect=lambda c, timeout=45: next(payloads)) as batch, \
             patch.object(self.adapter, "_app_server") as single:
            models = self.adapter.list_models()
        self.assertEqual(batch.call_count, 1)
        single.assert_not_called()
        self.assertEqual([(m["id"], m["name"]) for m in models],
                         [("m1", "M One"), ("m2", "m2")])

    def test_bridge_dispatch_uses_codex_sessions(self):
        import telegram_bridge as tg
        with patch.dict(os.environ, {"CODEX_HOME": str(self.root)}):
            sessions = tg.list_sessions({"TELECODE_AGENT": "codex"})
        self.assertEqual(sessions[0]["id"], SID)


if __name__ == "__main__":
    unittest.main()
