import re
import unittest

import setup_web


class WebSetupTests(unittest.TestCase):
    def test_token_format_is_strict(self):
        self.assertTrue(setup_web.TOKEN_RE.fullmatch("123456:abcdefghijklmnopqrstuvwxyz_ABC-123"))
        self.assertFalse(setup_web.TOKEN_RE.fullmatch("123:short"))
        self.assertFalse(setup_web.TOKEN_RE.fullmatch("12345:abcdefghijklmnopqrstuvwxyz;evil"))

    def test_server_uses_loopback_and_secret_is_not_printed(self):
        original = setup_web.webbrowser.open
        setup_web.webbrowser.open = lambda _url: False
        try:
            self.assertEqual(setup_web.run_setup_web(), 2)
        finally:
            setup_web.webbrowser.open = original


if __name__ == "__main__":
    unittest.main()
