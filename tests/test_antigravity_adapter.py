import json
import os
import pathlib
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from adapters.base import AgentSession
from adapters.antigravity import (
    AntigravityAdapter,
    AntigravityAdapterError,
    _clean_title,
    _antigravity_home,
    _strip_banner,
    _parse_time,
    _parse_workspace,
)
import setup_cli


class AntigravityAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.config_dir = self.root / ".gemini" / "antigravity-cli"
        self.config_dir.mkdir(parents=True)
        self.adapter = AntigravityAdapter(
            binary="agy",
            config_dir=self.config_dir,
            workspace=self.workspace,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_clean_title_and_strip_banner(self):
        self.assertEqual(_clean_title("\x1b[1mHello World\x1b[0m"), "Hello World")
        self.assertEqual(_clean_title("### `Title` **Here**"), "Title Here")

        raw_banner = "╭────────────────────────╮\n│ Antigravity CLI v1.5.3 │\n╰────────────────────────╯\nReal answer text"
        self.assertEqual(_strip_banner(raw_banner), "Real answer text")

    def test_parse_time_and_workspace(self):
        self.assertAlmostEqual(_parse_time(1700000000.0), 1700000000.0)
        iso = "2026-11-07T11:19:26.073408+00:00"
        self.assertGreater(_parse_time(iso), 0.0)

        ws_list = ["file:///home/user/project"]
        self.assertEqual(_parse_workspace(ws_list, self.workspace), "/home/user/project")
        ws_json = '["file:///home/user/project"]'
        self.assertEqual(_parse_workspace(ws_json, self.workspace), "/home/user/project")
        self.assertEqual(_parse_workspace("", self.workspace), str(self.workspace))

    def test_list_sessions_empty_when_no_db(self):
        self.assertEqual(self.adapter.list_sessions(), [])

    def test_list_sessions_from_sqlite_db(self):
        db_path = self.config_dir / "conversation_summaries.db"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE conversation_summaries (
                    conversation_id TEXT PRIMARY KEY,
                    title TEXT,
                    last_modified_time TEXT,
                    workspace_uris TEXT,
                    killed INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                INSERT INTO conversation_summaries (conversation_id, title, last_modified_time, workspace_uris, killed)
                VALUES
                    ('conv-1111-2222', 'Build TeleCode Bridge', '2026-11-08 12:00:00+00:00', '["file:///home/test"]', 0),
                    ('conv-3333-4444', 'Killed Conversation', '2026-11-08 11:00:00+00:00', '["file:///home/test"]', 1)
            """)

        sessions = self.adapter.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].id, "conv-1111-2222")
        self.assertEqual(sessions[0].title, "Build TeleCode Bridge")
        self.assertEqual(sessions[0].agent, "antigravity")

    def test_validate_session(self):
        db_path = self.config_dir / "conversation_summaries.db"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE conversation_summaries (
                    conversation_id TEXT PRIMARY KEY,
                    title TEXT,
                    last_modified_time TEXT,
                    workspace_uris TEXT,
                    killed INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                INSERT INTO conversation_summaries (conversation_id, title, last_modified_time, workspace_uris, killed)
                VALUES ('conv-1234', 'Active Task', '2026-11-08 10:00:00+00:00', '["file:///home/test"]', 0)
            """)

        valid = self.adapter.validate_session("conv-1234")
        self.assertIsNotNone(valid)
        self.assertEqual(valid.id, "conv-1234")
        self.assertEqual(valid.title, "Active Task")

        self.assertIsNone(self.adapter.validate_session("conv-does-not-exist"))

    def test_create_session(self):
        db_path = self.config_dir / "conversation_summaries.db"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE conversation_summaries (
                    conversation_id TEXT PRIMARY KEY,
                    title TEXT,
                    last_modified_time TEXT,
                    workspace_uris TEXT,
                    last_user_input_time TEXT
                )
            """)

        new_sess = self.adapter.create_session("Refactor UI Engine")
        self.assertIsNotNone(new_sess)
        self.assertEqual(new_sess.title, "Refactor UI Engine")
        self.assertEqual(new_sess.agent, "antigravity")

        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute("SELECT conversation_id, title FROM conversation_summaries WHERE conversation_id = ?", (new_sess.id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[1], "Refactor UI Engine")

    def test_send_message_success(self):
        with patch.object(self.adapter, "_resolve_binary", return_value="/usr/local/bin/agy"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="All tests passing smoothly", stderr="")
            reply = self.adapter.send_message("conv-1234", "Run test suite")
            self.assertEqual(reply, "All tests passing smoothly")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertEqual(args, ["/usr/local/bin/agy", "--conversation", "conv-1234", "--dangerously-skip-permissions", "--print", "Run test suite"])

    def test_send_message_missing_binary_raises_error(self):
        with patch.object(self.adapter, "_resolve_binary", return_value=None):
            with self.assertRaises(AntigravityAdapterError) as ctx:
                self.adapter.send_message("conv-1234", "Hello")
            self.assertIn("was not found", str(ctx.exception))

    def test_send_message_failure_surfaces_clean_error(self):
        with patch.object(self.adapter, "_resolve_binary", return_value="/usr/local/bin/agy"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error: context window exhausted")
            with self.assertRaises(AntigravityAdapterError) as ctx:
                self.adapter.send_message("conv-1234", "Do something")
            self.assertIn("context window exhausted", str(ctx.exception))

    def test_send_message_with_model(self):
        adapter = AntigravityAdapter(
            binary="agy",
            config_dir=self.config_dir,
            workspace=self.workspace,
            model="gemini-4-argon-high",
        )
        with patch.object(adapter, "_resolve_binary", return_value="/usr/local/bin/agy"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Model response", stderr="")
            reply = adapter.send_message("conv-1234", "Run test suite")
            self.assertEqual(reply, "Model response")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertEqual(args, [
                "/usr/local/bin/agy",
                "--conversation", "conv-1234",
                "--dangerously-skip-permissions",
                "--model", "gemini-4-argon-high",
                "--print", "Run test suite"
            ])

    def test_list_models_parsing_and_fallback(self):
        # 1. Output parsing from agy models
        stdout = (
            "⠋ Fetching available models...\n"
            "gemini-4-argon-medium     Gemini 4 Argon (Medium)\n"
            "claude-opus-5-5-high      Claude Opus 5.5 (High)\n"
            "gpt-oss-120b-medium       GPT-OSS 120B (Medium)\n"
        )
        with patch.object(self.adapter, "_resolve_binary", return_value="/usr/local/bin/agy"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=stdout, stderr="")
            models = self.adapter.list_models()
            self.assertEqual(len(models), 3)
            self.assertEqual(models[0]["id"], "gemini-4-argon-medium")
            self.assertEqual(models[0]["providerID"], "Google Gemini")
            self.assertEqual(models[1]["id"], "claude-opus-5-5-high")
            self.assertEqual(models[1]["providerID"], "Anthropic Claude")
            self.assertEqual(models[2]["id"], "gpt-oss-120b-medium")
            self.assertEqual(models[2]["providerID"], "OpenAI / OSS")

        # 2. Fallback when binary is missing
        with patch.object(self.adapter, "_resolve_binary", return_value=None):
            models = self.adapter.list_models()
            self.assertGreater(len(models), 5)
            self.assertTrue(any(m["id"] == "gemini-4-argon-medium" for m in models))

    def test_register_json_for_antigravity(self):
        settings_path = self.config_dir / "settings.json"
        settings_path.write_text(json.dumps({"model": "Gemini 3.8 Flash"}))
        host = ("Google Antigravity", "antigravity", [settings_path], True)
        updated = setup_cli.register_json(settings_path, host)
        parsed = json.loads(updated)
        self.assertIn("mcpServers", parsed)
        self.assertIn("telegram-bridge", parsed["mcpServers"])
        self.assertEqual(parsed["model"], "Gemini 3.8 Flash")


if __name__ == "__main__":
    unittest.main()
