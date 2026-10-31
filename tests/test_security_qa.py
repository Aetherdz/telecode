"""Focused regression checks for setup wizard security properties."""
import pathlib
import tempfile
import unittest

import setup_cli
import setup_web


class SetupSecurityTests(unittest.TestCase):
    def test_page_uses_escaped_client_data_and_csp_nonce(self):
        page = setup_web._page("secret-nonce", [{"name": "<img>", "key": "safe"}]).decode()
        self.assertIn('<script nonce="secret-nonce">', page)
        self.assertIn("&lt;img&gt;", page)
        self.assertNotIn("<img>", page)
        self.assertEqual(page.count("secret-nonce"), 2)  # form CSRF and script nonce

    def test_atomic_write_creates_private_file(self):
        with tempfile.TemporaryDirectory(dir=pathlib.Path.home()) as temp:
            target = pathlib.Path(temp) / "credentials"
            setup_cli.atomic_write(target, "secret=value\n")
            self.assertEqual(target.read_text(), "secret=value\n")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_url_token_randomized_per_launch_and_transport_policy_present(self):
        source = pathlib.Path(setup_web.__file__).read_text()
        self.assertIn("secrets.token_urlsafe(32)", source)
        self.assertIn("secrets.compare_digest", source)
        self.assertIn('self.headers.get("Origin")', source)
        self.assertIn('"Cache-Control", "no-store"', source)
        self.assertIn("server.server_close()", source)
        self.assertIn("script-src 'nonce-{token}'", source)


if __name__ == "__main__":
    unittest.main()
