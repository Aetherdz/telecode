import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from adapters.base import AgentSession
from adapters.hermes import HermesAdapter, HermesAdapterError
import setup_cli


class HermesAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.config_dir = self.root / ".hermes"
        self.config_dir.mkdir()
        self.adapter = HermesAdapter(
            binary="hermes",
            config_dir=self.config_dir,
            workspace=self.workspace,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_list_sessions_empty_when_no_sessions_dir(self):
        self.assertEqual(self.adapter.list_sessions(), [])

    def test_list_sessions_reads_json_and_jsonl(self):
        sessions_dir = self.config_dir / "sessions"
        sessions_dir.mkdir()

        # Session 1: JSON format
        s1 = sessions_dir / "session-1.json"
        s1.write_text(json.dumps({"title": "Fix login bug", "updated_at": 1700000000.0}))

        # Session 2: JSONL format
        s2 = sessions_dir / "session-2.jsonl"
        s2.write_text(json.dumps({"title": "Refactor database"}) + "\n")

        # Session 3: invalid ID
        s3 = sessions_dir / "invalid!id.json"
        s3.write_text(json.dumps({"title": "Bad ID"}))

        sessions = self.adapter.list_sessions()
        self.assertEqual(len(sessions), 2)
        sids = {s.id for s in sessions}
        self.assertIn("session-1", sids)
        self.assertIn("session-2", sids)
        titles = {s.title for s in sessions}
        self.assertIn("Fix login bug", titles)
        self.assertIn("Refactor database", titles)

    def test_validate_session(self):
        sessions_dir = self.config_dir / "sessions"
        sessions_dir.mkdir()
        (sessions_dir / "hermes-session-abc.json").write_text(json.dumps({"title": "Test Session"}))

        valid = self.adapter.validate_session("hermes-session-abc")
        self.assertIsNotNone(valid)
        self.assertEqual(valid.id, "hermes-session-abc")
        self.assertEqual(valid.title, "Test Session")

        invalid = self.adapter.validate_session("nonexistent-session")
        self.assertIsNone(invalid)

    def test_create_session_creates_file_and_returns_agent_session(self):
        session = self.adapter.create_session("Feature Implementation")
        self.assertIsNotNone(session)
        self.assertTrue(session.id.startswith("hermes-"))
        self.assertEqual(session.title, "Feature Implementation")
        self.assertEqual(session.agent, "hermes")

        # Verify it can be listed and validated
        valid = self.adapter.validate_session(session.id)
        self.assertIsNotNone(valid)
        self.assertEqual(valid.title, "Feature Implementation")

    def test_send_message_success(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Hermes response", stderr="")
            reply = self.adapter.send_message("sess-123", "Write unit test")
            self.assertEqual(reply, "Hermes response")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertEqual(args, ["hermes", "chat", "--resume", "sess-123", "--message", "Write unit test"])

    def test_send_message_failure_raises_adapter_error(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error: session not found")
            with self.assertRaises(HermesAdapterError) as ctx:
                self.adapter.send_message("sess-123", "Prompt")
            self.assertIn("Error: session not found", str(ctx.exception))

    def test_register_hermes_yaml_fresh_file(self):
        config_path = self.config_dir / "config.yaml"
        result = setup_cli.register_hermes_yaml(config_path)
        self.assertIn("mcp_servers:", result)
        self.assertIn("telegram-bridge:", result)
        self.assertIn(setup_cli.MCP_COMMAND[0], result)

    def test_register_hermes_yaml_preserves_existing_config(self):
        config_path = self.config_dir / "config.yaml"
        config_path.write_text("model: nous-hermes-3\ntemperature: 0.7\n")
        result = setup_cli.register_hermes_yaml(config_path)
        self.assertTrue(result.startswith("model: nous-hermes-3\ntemperature: 0.7\n"))
        self.assertIn("mcp_servers:", result)
        self.assertIn("telegram-bridge:", result)

    def test_register_hermes_yaml_merges_with_existing_mcp_servers(self):
        config_path = self.config_dir / "config.yaml"
        config_path.write_text("mcp_servers:\n  existing-server:\n    command: existing\n")
        result = setup_cli.register_hermes_yaml(config_path)
        self.assertIn("existing-server:", result)
        self.assertIn("telegram-bridge:", result)

    def test_register_hermes_yaml_refuses_overwrite_if_already_configured(self):
        config_path = self.config_dir / "config.yaml"
        config_path.write_text("mcp_servers:\n  telegram-bridge:\n    command: python\n")
        with self.assertRaises(ValueError) as ctx:
            setup_cli.register_hermes_yaml(config_path)
        self.assertIn("already configured", str(ctx.exception))

    def test_register_json_for_hermes(self):
        config_path = self.config_dir / "config.json"
        config_path.write_text(json.dumps({"model": "hermes-3"}))
        host = ("Hermes Agent", "hermes", [config_path], True)
        result = setup_cli.register_json(config_path, host)
        parsed = json.loads(result)
        self.assertEqual(parsed["model"], "hermes-3")
        self.assertIn("telegram-bridge", parsed["mcp_servers"])
        self.assertEqual(parsed["mcp_servers"]["telegram-bridge"]["command"], setup_cli.MCP_COMMAND[0])

    def test_backup_and_atomic_write_preserves_previous_file(self):
        config_path = self.config_dir / "config.yaml"
        original = "original: true\n"
        config_path.write_text(original)
        backup_path = setup_cli.backup(config_path)
        self.assertTrue(backup_path.is_file())
        self.assertEqual(backup_path.read_text(), original)

        new_content = setup_cli.register_hermes_yaml(config_path)
        setup_cli.atomic_write(config_path, new_content)
        self.assertTrue(config_path.is_file())
        self.assertIn("telegram-bridge:", config_path.read_text())
        self.assertIn("original: true", config_path.read_text())


if __name__ == "__main__":
    unittest.main()
