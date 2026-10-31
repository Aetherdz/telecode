import contextlib
import io
import unittest
from unittest import mock

import setup_web


class WebSetupTests(unittest.TestCase):
    def test_token_format_is_strict(self):
        self.assertTrue(setup_web.TOKEN_RE.fullmatch("123456:abcdefghijklmnopqrstuvwxyz_ABC-123"))
        self.assertFalse(setup_web.TOKEN_RE.fullmatch("123:short"))
        self.assertFalse(setup_web.TOKEN_RE.fullmatch("12345:abcdefghijklmnopqrstuvwxyz;evil"))

    def test_server_uses_loopback_and_secret_is_not_printed(self):
        output = io.StringIO()
        with mock.patch.object(setup_web.webbrowser, "open", return_value=False), contextlib.redirect_stdout(output):
            self.assertEqual(setup_web.run_setup_web(), 2)
        self.assertNotIn("session=", output.getvalue())

if __name__ == "__main__":
    unittest.main()
