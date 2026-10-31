import contextlib
import io
import json
import http.client
import pathlib
import threading
import unittest
import urllib.parse
from http.server import ThreadingHTTPServer
from unittest import mock

import setup_web


class WebSetupTests(unittest.TestCase):
    def test_token_format_is_strict(self):
        self.assertTrue(setup_web.TOKEN_RE.fullmatch("123456:abcdefghijklmnopqrstuvwxyz_ABC-123"))
        self.assertFalse(setup_web.TOKEN_RE.fullmatch("123:short"))
        self.assertFalse(setup_web.TOKEN_RE.fullmatch("12345:abcdefghijklmnopqrstuvwxyz;evil"))

    def test_server_uses_loopback_and_secret_is_not_printed(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(setup_web.run_setup_web(serve=False), 0)
        self.assertNotIn("session=", output.getvalue())

    def test_url_secret_is_consumed_cookie_set_and_redirected(self):
        captured = []

        class StopServer(ThreadingHTTPServer):
            def handle_request(self):
                raise KeyboardInterrupt

        with contextlib.redirect_stdout(io.StringIO()):
            setup_web.run_setup_web(browser_open=lambda url: captured.append(url), max_runtime=0.01, server_factory=ThreadingHTTPServer)
        self.assertEqual(len(captured), 1)
        query = urllib.parse.urlsplit(captured[0]).query
        self.assertIn("session=", query)

    def test_host_origin_and_csrf_policy_source_guards(self):
        source = pathlib.Path(setup_web.__file__).read_text(encoding="utf-8")
        self.assertIn('self.headers.get("Host", "")', source)
        self.assertIn('self.headers.get("X-CSRF-Token", "")', source)
        self.assertIn('source != origin', source)
        self.assertIn('ref_origin != origin', source)

    def test_session_url_not_logged_and_idle_runtime_is_configurable(self):
        output = io.StringIO()
        opened = []
        class StopServer(ThreadingHTTPServer):
            def handle_request(self):
                raise KeyboardInterrupt
        with contextlib.redirect_stdout(output):
            setup_web.run_setup_web(browser_open=lambda url: opened.append(url),
                                    max_runtime=0.01, server_factory=ThreadingHTTPServer)
        self.assertNotIn("session=", output.getvalue())
        self.assertIn("session=", opened[0])

if __name__ == "__main__":
    unittest.main()
