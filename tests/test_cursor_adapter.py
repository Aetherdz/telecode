import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from adapters.base import AgentSession
from adapters.cursor import CursorAdapter, CursorAdapterError


SID = "c6b62c6f-7ead-4fd6-9922-e952131177ff"


class CursorAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name).resolve()
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.adapter = CursorAdapter(workspace=self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def test_session_listing_reads_local_metadata_for_configured_workspace(self):
        config = self.root / "cursor-config"
        chat = config / "chats" / "workspace-hash" / SID
        chat.mkdir(parents=True)
        (chat / "meta.json").write_text(json.dumps({
            "schemaVersion": 1, "createdAtMs": 1700000000000,
            "updatedAtMs": 1700000005000, "hasConversation": True,
            "title": "Smoke chat", "cwd": str(self.workspace),
        }))
        adapter = CursorAdapter(workspace=self.workspace, config_dir=config)
        sessions = adapter.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].id, SID)
        self.assertEqual(sessions[0].title, "Smoke chat")
        self.assertEqual(sessions[0].directory, str(self.workspace.resolve()))

    def test_session_listing_includes_other_workspaces_and_skips_corrupt_metadata(self):
        config = self.root / "cursor-config"
        other_workspace = self.root / "other-project"
        other_workspace.mkdir()
        other = config / "chats" / "workspace-hash" / SID
        other.mkdir(parents=True)
        (other / "meta.json").write_text(json.dumps({"cwd": str(other_workspace)}))
        bad = config / "chats" / "workspace-hash" / "01234567-89ab-cdef-0123-456789abcdef"
        bad.mkdir()
        (bad / "meta.json").write_text("not json")
        adapter = CursorAdapter(workspace=self.workspace, config_dir=config)
        sessions = adapter.list_sessions()
        self.assertEqual([session.id for session in sessions], [SID])
        self.assertEqual(sessions[0].directory, str(other_workspace.resolve()))

    def test_session_title_falls_back_to_bounded_first_user_prompt(self):
        config = self.root / "cursor-config"
        chat = config / "chats" / "workspace-hash" / SID
        chat.mkdir(parents=True)
        (chat / "meta.json").write_text(json.dumps({
            "cwd": str(self.workspace), "updatedAtMs": 1700000000000,
        }))
        transcript = config / "projects" / "workspace" / "agent-transcripts" / SID
        transcript.mkdir(parents=True)
        (transcript / f"{SID}.jsonl").write_text(json.dumps({
            "role": "user", "message": {"content": [{"type": "text", "text":
                "<timestamp>today</timestamp><user_query>Fix the login flow please</user_query>"}]}
        }) + "\n")
        adapter = CursorAdapter(workspace=self.workspace, config_dir=config)
        self.assertEqual(adapter.list_sessions()[0].title, "Fix the login flow please")

    def test_validate_session_requires_id_shape(self):
        with patch.object(self.adapter, "list_sessions", return_value=[
                AgentSession(SID, "Listed", str(self.workspace), "cursor")]):
            self.assertEqual(self.adapter.validate_session(SID).id, SID)
        self.assertIsNone(self.adapter.validate_session("bad id"))

    def test_validate_session_rejects_well_formed_id_not_in_cursor_metadata(self):
        with patch.object(self.adapter, "list_sessions", return_value=[]):
            self.assertIsNone(self.adapter.validate_session(SID))

    def test_validate_session_returns_metadata_workspace(self):
        other = self.root / "other-project"
        other.mkdir()
        listed = AgentSession(SID, "Listed", str(other), "cursor")
        with patch.object(self.adapter, "list_sessions", return_value=[listed]):
            self.assertEqual(self.adapter.validate_session(SID), listed)

    def test_argv_resumes_thread_in_print_mode(self):
        with patch.object(self.adapter, "list_sessions", return_value=[
                AgentSession(SID, "Listed", str(self.workspace), "cursor")]):
            self.assertEqual(self.adapter.build_argv(SID, "hello"),
                             ["agent", "--resume", SID, "--print", "--output-format", "text", "hello"])

    def test_argv_passes_selected_model(self):
        adapter = CursorAdapter(workspace=self.workspace, model="gpt-5.3-codex")
        with patch.object(adapter, "list_sessions", return_value=[
                AgentSession(SID, "Listed", str(self.workspace), "cursor")]):
            self.assertEqual(adapter.build_argv(SID, "hello"),
                             ["agent", "--resume", SID, "--print", "--output-format", "text",
                              "--model", "gpt-5.3-codex", "hello"])

    def test_send_message_uses_workspace_and_returns_text(self):
        result = type("Result", (), {"returncode": 0, "stdout": "answer\n", "stderr": ""})()
        listed = AgentSession(SID, "Listed", str(self.workspace), "cursor")
        with patch.object(self.adapter, "list_sessions", return_value=[listed]), \
             patch("adapters.cursor.subprocess.run", return_value=result) as run:
            self.assertEqual(self.adapter.send_message(SID, "hello"), "answer")
        self.assertEqual(run.call_args.kwargs["cwd"], str(self.workspace.resolve()))
        self.assertEqual(run.call_args.kwargs["timeout"], 600)

    def test_send_message_uses_session_workspace_from_metadata(self):
        other_workspace = self.root / "other-project"
        other_workspace.mkdir()
        result = type("Result", (), {"returncode": 0, "stdout": "answer", "stderr": ""})()
        with patch.object(self.adapter, "list_sessions", return_value=[
                AgentSession(SID, "Other", str(other_workspace), "cursor")]), \
             patch("adapters.cursor.subprocess.run", return_value=result) as run:
            self.assertEqual(self.adapter.send_message(SID, "hello"), "answer")
        self.assertEqual(run.call_args.kwargs["cwd"], str(other_workspace.resolve()))

    def test_send_message_rejects_unknown_uuid_instead_of_falling_back_to_workspace(self):
        with patch.object(self.adapter, "list_sessions", return_value=[]), \
             patch("adapters.cursor.subprocess.run") as run:
            with self.assertRaisesRegex(CursorAdapterError, "no longer available"):
                self.adapter.send_message(SID, "hello")
        run.assert_not_called()

    def test_create_session_runs_cursor_create_chat(self):
        result = type("Result", (), {"returncode": 0, "stdout": SID + "\n", "stderr": ""})()
        with patch("adapters.cursor.subprocess.run", return_value=result) as run:
            session = self.adapter.create_session("  A   new chat  ")
        self.assertEqual(session.id, SID)
        self.assertEqual(session.title, "A new chat")
        self.assertEqual(session.directory, str(self.workspace.resolve()))
        self.assertEqual(run.call_args.args[0], ["agent", "create-chat"])
        self.assertEqual(run.call_args.kwargs["cwd"], str(self.workspace.resolve()))

    def test_create_session_rejects_invalid_cli_output(self):
        result = type("Result", (), {"returncode": 0, "stdout": "not-an-id\n", "stderr": ""})()
        with patch("adapters.cursor.subprocess.run", return_value=result):
            with self.assertRaisesRegex(CursorAdapterError, "valid session ID"):
                self.adapter.create_session("A new chat")

    def test_bridge_session_creation_uses_cursor_cli(self):
        import telegram_bridge as tg
        cfg = {"TELECODE_AGENT": "cursor", "CURSOR_WORKSPACE": str(self.workspace)}
        result = type("Result", (), {"returncode": 0, "stdout": SID + "\n", "stderr": ""})()
        with patch("adapters.cursor.subprocess.run", return_value=result):
            session = tg.create_session(cfg, "From Telegram")
        self.assertEqual(session["id"], SID)
        self.assertEqual(session["title"], "From Telegram")
        self.assertEqual(session["agent"], "cursor")

    def test_cli_error_is_reported(self):
        result = type("Result", (), {"returncode": 1, "stdout": "", "stderr": "bad thread"})()
        with patch.object(self.adapter, "list_sessions", return_value=[
                AgentSession(SID, "Listed", str(self.workspace), "cursor")]), \
             patch("adapters.cursor.subprocess.run", return_value=result):
            with self.assertRaisesRegex(CursorAdapterError, "bad thread"):
                self.adapter.send_message(SID, "hello")

    def test_bridge_supports_manual_session_selection(self):
        import telegram_bridge as tg
        cfg = {"TELECODE_AGENT": "cursor", "CURSOR_WORKSPACE": str(self.workspace)}
        empty_config = self.root / "empty-cursor-config"
        empty_config.mkdir()
        with patch.dict("os.environ", {"CURSOR_CONFIG_DIR": str(empty_config)}):
            self.assertEqual(tg.list_sessions(cfg), [])
            self.assertIsNone(tg._session_by_id(cfg, SID))
        config = self.root / "bridge-cursor-config"
        chat = config / "chats" / "workspace-hash" / SID
        chat.mkdir(parents=True)
        (chat / "meta.json").write_text(json.dumps({
            "title": "Listed from bridge", "cwd": str(self.workspace),
            "updatedAtMs": 1700000000000,
        }))
        with patch.dict("os.environ", {"CURSOR_CONFIG_DIR": str(config)}):
            listed = tg.list_sessions(cfg)
        self.assertEqual(listed[0]["id"], SID)
        self.assertEqual(listed[0]["title"], "Listed from bridge")

    def test_telegram_picker_selects_cursor_uuid_session(self):
        import telegram_bridge as tg
        cfg = {"TELECODE_AGENT": "cursor", "CURSOR_WORKSPACE": str(self.workspace)}
        session = {"id": SID, "title": "Cursor project chat", "directory": str(self.workspace)}
        tb_state = (tg.ACTIVE_PICKER, list(tg.SESSION_SNAPSHOT), dict(tg.SESSION_BUTTONS))
        try:
            tg.ACTIVE_PICKER = "sessions"
            tg.SESSION_SNAPSHOT = [session]
            tg.SESSION_BUTTONS.clear()
            tg.SESSION_BUTTONS["1. Cursor project chat"] = SID
            with patch.object(tg, "_session_by_id", return_value=session), \
                 patch.object(tg, "_set_active_session") as select, \
                 patch.object(tg, "send_text"), patch.object(tg, "_send_keyboard"):
                self.assertTrue(tg.handle_control_message(cfg, {}, "1. Cursor project chat"))
            select.assert_called_once_with(session)
        finally:
            tg.ACTIVE_PICKER = tb_state[0]
            tg.SESSION_SNAPSHOT = tb_state[1]
            tg.SESSION_BUTTONS.clear()
            tg.SESSION_BUTTONS.update(tb_state[2])


if __name__ == "__main__":
    unittest.main()
