import os
import unittest
from unittest import mock

from telegram_bridge import ui


class UIHelpersTests(unittest.TestCase):
    def test_no_color_disables_ansi(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}), mock.patch("sys.stdout.isatty", return_value=True):
            self.assertFalse(ui.supports_color())
            self.assertEqual(ui.accent("text"), "text")

    def test_non_tty_disables_color(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("sys.stdout.isatty", return_value=False):
            self.assertFalse(ui.supports_color())

    def test_mask_helpers_never_return_full_secret(self):
        token = "123456:abcdefghijklmnopqrstuvwxyz_123456"
        self.assertNotEqual(ui.mask_token(token), token)
        self.assertNotIn(token.split(":", 1)[1], ui.mask_token(token))
        chat = "123456789012345"
        self.assertNotEqual(ui.mask_value(chat), chat)
        self.assertTrue(ui.mask_value(chat).endswith("2345"))

    def test_visible_width_strips_ansi_and_handles_wide_chars(self):
        self.assertEqual(ui.visible_width("\033[31m界e\u0301\033[0m"), 3)

    def test_mask_chat_id_is_stable_and_short_ids_fully_hidden(self):
        from telegram_bridge.detection import mask_chat_id
        self.assertEqual(mask_chat_id("123456789"), "••••6789")
        self.assertEqual(mask_chat_id("12"), "••••")


if __name__ == "__main__":
    unittest.main()
