import json
import os
import pathlib
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from adapters.base import AgentSession
from adapters.hermes import HermesAdapter, HermesAdapterError, _clean_title, _hermes_home, _strip_banner
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

    def test_list_sessions_strips_ansi_and_markdown(self):
        sessions_dir = self.config_dir / "sessions"
        sessions_dir.mkdir()

        s1 = sessions_dir / "session-ansi.json"
        s1.write_text(json.dumps({"title": "\x1b[32mFix\x1b[0m \x1b[1mLogin Issue\x1b[0m"}))

        s2 = sessions_dir / "session-md.json"
        s2.write_text(json.dumps({"title": "### **Add Unit Tests**"}))

        sessions = self.adapter.list_sessions()
        titles = {s.title for s in sessions}
        self.assertIn("Fix Login Issue", titles)
        self.assertIn("Add Unit Tests", titles)

    def test_list_sessions_reads_from_state_db(self):
        db_path = self.config_dir / "state.db"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    title TEXT,
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    workspace TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
                ("session-sql-1", "cli", "\x1b[34mSQLite Task\x1b[0m", 1700000100.0, 1700000200.0, str(self.workspace)),
            )
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
                ("session-sql-2", "cli", "## **Refactor Mixins**", 1700000050.0, 1700000090.0, str(self.workspace)),
            )

        sessions = self.adapter.list_sessions()
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].id, "session-sql-1")
        self.assertEqual(sessions[0].title, "SQLite Task")
        self.assertEqual(sessions[1].id, "session-sql-2")
        self.assertEqual(sessions[1].title, "Refactor Mixins")

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

    def test_validate_session_fast_path_jsonl_and_sqlite(self):
        sessions_dir = self.config_dir / "sessions"
        sessions_dir.mkdir()
        (sessions_dir / "hermes-session-jsonl.jsonl").write_text(json.dumps({"title": "Fast JSONL"}) + "\n")

        valid_jsonl = self.adapter.validate_session("hermes-session-jsonl")
        self.assertIsNotNone(valid_jsonl)
        self.assertEqual(valid_jsonl.title, "Fast JSONL")

        db_path = self.config_dir / "state.db"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    source TEXT,
                    title TEXT,
                    started_at REAL,
                    ended_at REAL,
                    workspace TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
                ("hermes-session-db", "cli", "DB Fast Session", 1700000000.0, 1700000100.0, str(self.workspace)),
            )

        valid_db = self.adapter.validate_session("hermes-session-db")
        self.assertIsNotNone(valid_db)
        self.assertEqual(valid_db.title, "DB Fast Session")

    def test_validate_session_rejects_malformed_id(self):
        self.assertIsNone(self.adapter.validate_session(""))
        self.assertIsNone(self.adapter.validate_session("../evil"))
        self.assertIsNone(self.adapter.validate_session("id with spaces"))

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

    def test_create_session_cleans_title_and_registers_state_db(self):
        db_path = self.config_dir / "state.db"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    source TEXT,
                    title TEXT,
                    started_at REAL,
                    ended_at REAL,
                    workspace TEXT
                )
                """
            )

        session = self.adapter.create_session("\x1b[31m### **Hotfix Title**\x1b[0m")
        self.assertEqual(session.title, "Hotfix Title")

        # Verify record in SQLite database
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, workspace FROM sessions WHERE id = ?", (session.id,))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[1], "Hotfix Title")

    def test_send_message_success(self):
        with patch("shutil.which", return_value="/usr/local/bin/hermes"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Hermes response", stderr="")
            reply = self.adapter.send_message("sess-123", "Write unit test")
            self.assertEqual(reply, "Hermes response")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertEqual(args, ["hermes", "chat", "--resume", "sess-123", "-q", "Write unit test"])
            kwargs = mock_run.call_args[1]
            self.assertEqual(kwargs["env"]["NO_COLOR"], "1")
            self.assertEqual(kwargs["env"]["TERM"], "dumb")
            self.assertEqual(kwargs["env"]["HERMES_HOME"], str(self.config_dir))

    def test_send_message_strips_terminal_escapes_and_banner(self):
        raw_stdout = (
            "\x1b[36m╭─ Hermes Agent v0.8.2 ─────────────╮\x1b[0m\n"
            "\x1b[36m│ Tools: 14 loaded · Model: Hermes 3 │\x1b[0m\n"
            "\x1b[36m╰───────────────────────────────────╯\x1b[0m\n"
            "\n"
            "\x1b[32mCode generation complete.\x1b[0m"
        )
        with patch("shutil.which", return_value="/usr/local/bin/hermes"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=raw_stdout, stderr="")
            reply = self.adapter.send_message("sess-123", "Generate code")
            self.assertEqual(reply, "Code generation complete.")

    def test_send_message_missing_binary_raises_actionable_error(self):
        with patch("shutil.which", return_value=None):
            with self.assertRaises(HermesAdapterError) as ctx:
                self.adapter.send_message("sess-123", "Prompt")
            err_msg = str(ctx.exception)
            self.assertIn("not installed or not found in PATH", err_msg)
            self.assertIn("pip install hermes-agent", err_msg)
            self.assertIn("pipx install hermes-agent", err_msg)

    def test_send_message_filenotfound_raises_actionable_error(self):
        with patch("shutil.which", return_value="/usr/local/bin/hermes"), \
             patch("subprocess.run", side_effect=FileNotFoundError("No such file")):
            with self.assertRaises(HermesAdapterError) as ctx:
                self.adapter.send_message("sess-123", "Prompt")
            err_msg = str(ctx.exception)
            self.assertIn("pip install hermes-agent", err_msg)

    def test_send_message_failure_raises_adapter_error(self):
        with patch("shutil.which", return_value="/usr/local/bin/hermes"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error: session not found")
            with self.assertRaises(HermesAdapterError) as ctx:
                self.adapter.send_message("sess-123", "Prompt")
            self.assertIn("Error: session not found", str(ctx.exception))

    def test_send_message_timeout_raises_adapter_error(self):
        with patch("shutil.which", return_value="/usr/local/bin/hermes"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["hermes"], 5)):
            with self.assertRaises(HermesAdapterError) as ctx:
                self.adapter.send_message("sess-123", "Prompt")
            self.assertIn("timed out", str(ctx.exception))

    def test_send_message_invalid_session_id_returns_none(self):
        self.assertIsNone(self.adapter.send_message("", "test"))
        self.assertIsNone(self.adapter.send_message("bad id!", "test"))

    def test_clean_title_helper(self):
        self.assertEqual(_clean_title(""), "")
        self.assertEqual(_clean_title("\x1b[31;1mError Handler\x1b[0m"), "Error Handler")
        self.assertEqual(_clean_title("### Refactor `Auth` **Service**"), "Refactor Auth Service")
        self.assertEqual(_clean_title("   multiple    spaces   "), "multiple spaces")

    def test_strip_banner_helper(self):
        self.assertEqual(_strip_banner(""), "")
        self.assertEqual(_strip_banner("Plain text"), "Plain text")
        banner = "╭─ Hermes Agent ─╮\n│ Welcome       │\n╰───────────────╯\n\nActual response"
        self.assertEqual(_strip_banner(banner), "Actual response")

    def test_hermes_home_prefers_hermes_home_env(self):
        custom = str(self.root / "custom_hermes")
        with patch.dict(os.environ, {"HERMES_HOME": custom}):
            self.assertEqual(_hermes_home(), pathlib.Path(custom))

        with patch.dict(os.environ, {"HERMES_CONFIG_DIR": custom}, clear=True):
            self.assertEqual(_hermes_home(), pathlib.Path(custom))

    def test_register_hermes_yaml_fresh_file(self):
        config_path = self.config_dir / "config.yaml"
        result = setup_cli.register_hermes_yaml(config_path)
        self.assertIn("mcp_servers:", result)
        self.assertIn("telegram-bridge:", result)
        self.assertIn(setup_cli.MCP_COMMAND[0], result)
        self.assertIn("TELEGRAM_BRIDGE_HOME", result)

    def test_register_hermes_yaml_preserves_existing_config(self):
        config_path = self.config_dir / "config.yaml"
        config_path.write_text("model: nous-hermes-3\ntemperature: 0.7\n")
        result = setup_cli.register_hermes_yaml(config_path)
        self.assertTrue(result.startswith("model: nous-hermes-3\ntemperature: 0.7\n"))
        self.assertIn("mcp_servers:", result)
        self.assertIn("telegram-bridge:", result)
        self.assertIn("TELEGRAM_BRIDGE_HOME", result)

    def test_register_hermes_yaml_merges_with_existing_mcp_servers(self):
        config_path = self.config_dir / "config.yaml"
        config_path.write_text("mcp_servers:\n  existing-server:\n    command: existing\n")
        result = setup_cli.register_hermes_yaml(config_path)
        self.assertIn("existing-server:", result)
        self.assertIn("telegram-bridge:", result)
        self.assertIn("TELEGRAM_BRIDGE_HOME", result)

    def test_register_hermes_yaml_with_empty_curly_braces(self):
        config_path = self.config_dir / "config.yaml"
        config_path.write_text("mcp_servers: {}\nother_key: true\n")
        result = setup_cli.register_hermes_yaml(config_path)
        self.assertIn("mcp_servers:", result)
        self.assertIn("telegram-bridge:", result)
        self.assertIn("other_key: true", result)

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
        self.assertIn("env", parsed["mcp_servers"]["telegram-bridge"])
        self.assertEqual(
            parsed["mcp_servers"]["telegram-bridge"]["env"]["TELEGRAM_BRIDGE_HOME"],
            str(setup_cli.RUNTIME_CONFIG),
        )

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
