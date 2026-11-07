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

    def test_send_menu_option_shows_usage(self):
        with patch("builtins.input", return_value="6"), patch("builtins.print") as output:
            self.assertEqual(cli.cmd_menu(), 0)
        self.assertIn("telecode send TEXT", " ".join(str(call.args) for call in output.call_args_list))

    def test_help_menu_option_prints_usage(self):
        with patch("builtins.input", return_value="8"), patch("builtins.print") as output:
            self.assertEqual(cli.cmd_menu(), 0)
        self.assertIn("Usage: telecode", " ".join(str(call.args) for call in output.call_args_list))

    def test_status_menu_option_calls_cmd_status(self):
        with patch("builtins.input", return_value="2"), patch.object(cli, "cmd_status", return_value=0) as mock_st, patch("builtins.print"):
            self.assertEqual(cli.cmd_menu(), 0)
            mock_st.assert_called_once()


if __name__ == "__main__":
    unittest.main()
