import importlib.util
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import sys

from telegram_bridge import cli
import telegram_bridge as tb


class AgentCliTests(unittest.TestCase):
    def test_cmd_agent_no_args_displays_card(self):
        cfg = {"TELECODE_AGENT": "opencode", "TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "load_env", return_value=cfg), \
             patch.object(tb, "resolve_session", return_value=("ses_123", "active")), \
             patch("builtins.print") as mock_print:
            rc = cli.cmd_agent([])
            self.assertEqual(rc, 0)
            printed = " ".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("OpenCode", printed)
            self.assertIn("Hermes Agent", printed)
            self.assertIn("Google Antigravity", printed)

    def test_cmd_agent_switch_antigravity(self):
        cfg = {"TELECODE_AGENT": "opencode", "TG_AGENT": "opencode"}
        with patch.object(tb, "load_env", return_value=cfg), \
             patch.object(tb, "switch_active_agent", return_value={"id": "conv-999", "title": "New AGY Session"}) as mock_switch, \
             patch("builtins.print") as mock_print:
            rc = cli.cmd_agent(["antigravity"])
            self.assertEqual(rc, 0)
            mock_switch.assert_called_once_with(cfg, "antigravity")
            printed = " ".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("Google Antigravity", printed)
            self.assertIn("conv-999", printed)

    def test_cmd_agent_switch_success(self):
        cfg = {"TELECODE_AGENT": "opencode", "TG_AGENT": "opencode"}
        with patch.object(tb, "load_env", return_value=cfg), \
             patch.object(tb, "switch_active_agent", return_value={"id": "hermes-1", "title": "New Session"}) as mock_switch, \
             patch("builtins.print") as mock_print:
            rc = cli.cmd_agent(["hermes"])
            self.assertEqual(rc, 0)
            mock_switch.assert_called_once_with(cfg, "hermes")
            printed = " ".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("Hermes Agent", printed)
            self.assertIn("hermes-1", printed)

    def test_cmd_agent_invalid_name_fails(self):
        cfg = {"TELECODE_AGENT": "opencode"}
        with patch.object(tb, "load_env", return_value=cfg), \
             patch.object(tb, "switch_active_agent") as mock_switch, \
             patch("sys.stderr.write") as mock_err:
            rc = cli.cmd_agent(["nonexistent_agent_xyz"])
            self.assertEqual(rc, 2)
            mock_switch.assert_not_called()

    def test_cmd_status_includes_agent(self):
        cfg = {"TELECODE_AGENT": "hermes", "TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "load_env", return_value=cfg), \
             patch.object(tb, "api", return_value={"result": {"username": "test_bot", "id": 123}}), \
             patch.object(tb, "resolve_session", return_value=("hermes-abc", "active")), \
             patch("builtins.print") as mock_print:
            rc = cli.cmd_status()
            self.assertEqual(rc, 0)
            printed = " ".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("Agent", printed)
            self.assertIn("Hermes Agent", printed)

    def test_check_env_reload_updates_cfg_in_place(self):
        with tempfile.TemporaryDirectory() as temp:
            env_file = pathlib.Path(temp) / "telegram.env"
            env_file.write_text("TELECODE_AGENT=opencode\nTG_BOT_TOKEN=tok1\nTG_CHAT_ID=123\n")
            cfg = {"TELECODE_AGENT": "opencode", "TG_BOT_TOKEN": "tok1", "TG_CHAT_ID": "123"}
            mtime1 = env_file.stat().st_mtime

            from telegram_bridge.listener import _check_env_reload
            with patch.object(tb, "ENV", env_file):
                # No change
                mtime2 = _check_env_reload(cfg, mtime1)
                self.assertEqual(mtime2, mtime1)
                self.assertEqual(cfg["TELECODE_AGENT"], "opencode")

                # Update env file
                import time
                time.sleep(0.05)
                env_file.write_text("TELECODE_AGENT=hermes\nTG_BOT_TOKEN=tok1\nTG_CHAT_ID=123\n")
                mtime3 = _check_env_reload(cfg, mtime1)
                self.assertGreater(mtime3, mtime1)
                self.assertEqual(cfg["TELECODE_AGENT"], "hermes")


if __name__ == "__main__":
    unittest.main()
