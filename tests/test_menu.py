import unittest
from unittest.mock import patch

from telegram_bridge import cli


class MenuTests(unittest.TestCase):
    def test_menu_displays_organized_command_list(self):
        with patch("builtins.input", return_value="q"), patch("builtins.print") as output:
            self.assertEqual(cli.cmd_menu(), 0)
        text = "\n".join(str(call.args[0]) for call in output.call_args_list if call.args)
        for label in ("Setup wizard", "Show status", "Start listener", "Read messages",
                      "Wait for message", "Send a message", "Find chat ID", "Help / commands", "Exit"):
            self.assertIn(label, text)

    def test_invalid_menu_choice_retries_until_exit(self):
        with patch("builtins.input", side_effect=["0", "q"]), patch("builtins.print"):
            self.assertEqual(cli.cmd_menu(), 0)

    def test_wait_menu_option_shows_usage(self):
        with patch("builtins.input", return_value="5"), patch("builtins.print") as output:
            self.assertEqual(cli.cmd_menu(), 0)
        self.assertIn("telecode wait [SECONDS]", " ".join(str(call.args) for call in output.call_args_list))

    def test_send_menu_option_calls_cmd_send(self):
        with patch("builtins.input", return_value="6"), patch.object(cli, "cmd_send", return_value=0) as mock_send, patch("builtins.print"):
            self.assertEqual(cli.cmd_menu(), 0)
            mock_send.assert_called_once()

    def test_help_menu_option_prints_usage(self):
        with patch("builtins.input", return_value="8"), patch("builtins.print") as output:
            self.assertEqual(cli.cmd_menu(), 0)
        self.assertIn("Usage: telecode", " ".join(str(call.args) for call in output.call_args_list))

    def test_status_menu_option_calls_cmd_status(self):
        with patch("builtins.input", return_value="2"), patch.object(cli, "cmd_status", return_value=0) as mock_st, patch("builtins.print"):
            self.assertEqual(cli.cmd_menu(), 0)
            mock_st.assert_called_once()

    def test_setup_menu_option_calls_cmd_setup(self):
        with patch("builtins.input", return_value="1"), patch.object(cli, "cmd_setup", return_value=0) as mock_su, patch("builtins.print"):
            self.assertEqual(cli.cmd_menu(), 0)
            mock_su.assert_called_once()

    def test_cmd_setup_web_flag_routes_to_web_setup(self):
        with patch.object(cli, "run_web_setup", return_value=0) as mock_web:
            self.assertEqual(cli.cmd_setup(["--web"]), 0)
            mock_web.assert_called_once()

    def test_cmd_setup_cli_flag_routes_to_cli_setup(self):
        with patch.object(cli, "run_cli_setup", return_value=0) as mock_cli:
            self.assertEqual(cli.cmd_setup(["--cli"]), 0)
            mock_cli.assert_called_once()

    def test_cmd_setup_interactive_browser_selection(self):
        with patch("builtins.input", return_value="1"), patch.object(cli, "run_web_setup", return_value=0) as mock_web, patch("builtins.print"):
            self.assertEqual(cli.cmd_setup([]), 0)
            mock_web.assert_called_once()

    def test_cmd_setup_interactive_terminal_selection(self):
        with patch("builtins.input", return_value="2"), patch.object(cli, "run_cli_setup", return_value=0) as mock_cli, patch("builtins.print"):
            self.assertEqual(cli.cmd_setup([]), 0)
            mock_cli.assert_called_once()

    def test_cmd_setup_interactive_cancel(self):
        with patch("builtins.input", return_value="3"), patch("builtins.print"):
            self.assertEqual(cli.cmd_setup([]), 0)


class SendCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = __import__("tempfile").TemporaryDirectory()
        self.root = __import__("pathlib").Path(self.temp_dir.name)
        self.sample_file = self.root / "report.txt"
        self.sample_file.write_text("Hello from file")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_send_text_argument(self):
        cfg = {"TG_BOT_TOKEN": "bot123:ABC", "TG_CHAT_ID": "456"}
        with patch("telegram_bridge.load_env", return_value=cfg), \
             patch("telegram_bridge.send_text", return_value=101) as mock_send, \
             patch("builtins.print"):
            rc = cli.cmd_send(["Hello", "Telegram"])
            self.assertEqual(rc, 0)
            mock_send.assert_called_once_with(cfg, "Hello Telegram")

    def test_send_file_argument_direct(self):
        cfg = {"TG_BOT_TOKEN": "bot123:ABC", "TG_CHAT_ID": "456"}
        with patch("telegram_bridge.load_env", return_value=cfg), \
             patch("telegram_bridge.send_file", return_value=102) as mock_send, \
             patch("builtins.print"):
            rc = cli.cmd_send([str(self.sample_file), "Monthly", "Report"])
            self.assertEqual(rc, 0)
            mock_send.assert_called_once_with(cfg, self.sample_file, "Monthly Report")

    def test_send_file_flag(self):
        cfg = {"TG_BOT_TOKEN": "bot123:ABC", "TG_CHAT_ID": "456"}
        with patch("telegram_bridge.load_env", return_value=cfg), \
             patch("telegram_bridge.send_file", return_value=103) as mock_send, \
             patch("builtins.print"):
            rc = cli.cmd_send(["--file", str(self.sample_file), "My Caption"])
            self.assertEqual(rc, 0)
            mock_send.assert_called_once_with(cfg, self.sample_file, "My Caption")

    def test_send_short_f_flag(self):
        cfg = {"TG_BOT_TOKEN": "bot123:ABC", "TG_CHAT_ID": "456"}
        with patch("telegram_bridge.load_env", return_value=cfg), \
             patch("telegram_bridge.send_file", return_value=104) as mock_send, \
             patch("builtins.print"):
            rc = cli.cmd_send(["-f", str(self.sample_file)])
            self.assertEqual(rc, 0)
            mock_send.assert_called_once_with(cfg, self.sample_file, "")

    def test_send_file_not_found(self):
        cfg = {"TG_BOT_TOKEN": "bot123:ABC", "TG_CHAT_ID": "456"}
        with patch("telegram_bridge.load_env", return_value=cfg), \
             patch("builtins.print"):
            rc = cli.cmd_send(["--file", str(self.root / "nonexistent.dat")])
            self.assertEqual(rc, 2)

    def test_send_interactive_text(self):
        cfg = {"TG_BOT_TOKEN": "bot123:ABC", "TG_CHAT_ID": "456"}
        with patch("telegram_bridge.load_env", return_value=cfg), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="Interactive hello"), \
             patch("telegram_bridge.send_text", return_value=105) as mock_send, \
             patch("builtins.print"):
            rc = cli.cmd_send([])
            self.assertEqual(rc, 0)
            mock_send.assert_called_once_with(cfg, "Interactive hello")

    def test_send_interactive_file_with_caption(self):
        cfg = {"TG_BOT_TOKEN": "bot123:ABC", "TG_CHAT_ID": "456"}
        with patch("telegram_bridge.load_env", return_value=cfg), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", side_effect=[str(self.sample_file), "Cool caption"]), \
             patch("telegram_bridge.send_file", return_value=106) as mock_send, \
             patch("builtins.print"):
            rc = cli.cmd_send([])
            self.assertEqual(rc, 0)
            mock_send.assert_called_once_with(cfg, self.sample_file, "Cool caption")

    def test_send_stdin_pipe(self):
        cfg = {"TG_BOT_TOKEN": "bot123:ABC", "TG_CHAT_ID": "456"}
        with patch("telegram_bridge.load_env", return_value=cfg), \
             patch("sys.stdin.isatty", return_value=False), \
             patch("sys.stdin.read", return_value="Piped input message"), \
             patch("telegram_bridge.send_text", return_value=107) as mock_send, \
             patch("builtins.print"):
            rc = cli.cmd_send([])
            self.assertEqual(rc, 0)
            mock_send.assert_called_once_with(cfg, "Piped input message")

    def test_send_config_error(self):
        with patch("telegram_bridge.load_env", side_effect=FileNotFoundError("no env")), \
             patch("builtins.print"):
            rc = cli.cmd_send(["Hello"])
            self.assertEqual(rc, 1)

    def test_sendfile_dedicated_alias(self):
        cfg = {"TG_BOT_TOKEN": "bot123:ABC", "TG_CHAT_ID": "456"}
        with patch("telegram_bridge.load_env", return_value=cfg), \
             patch("telegram_bridge.send_file", return_value=108) as mock_send, \
             patch("builtins.print"):
            rc = cli.cmd_sendfile([str(self.sample_file), "Alias caption"])
            self.assertEqual(rc, 0)
            mock_send.assert_called_once_with(cfg, self.sample_file, "Alias caption")


if __name__ == "__main__":
    unittest.main()
