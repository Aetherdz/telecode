#!/usr/bin/env python3
"""Temporary, loopback-only browser setup wizard."""
from __future__ import annotations

import http.server
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

import setup_cli

HOST = "127.0.0.1"
SESSION_SECONDS = 15 * 60
MAX_BODY = 16 * 1024
WEB = Path(__file__).resolve().parent / "telegram_bridge" / "web"
TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{20,}\Z")


def _telegram(method: str, token: str, params: dict | None = None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode() if params else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    with urllib.request.urlopen(request, timeout=8) as response:
        result = json.loads(response.read(65536))
    if not isinstance(result, dict) or not result.get("ok"):
        raise ValueError("Telegram rejected the request")
    return result.get("result")


def run_setup_web() -> int:
    secret = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    started, finished = time.monotonic(), threading.Event()
    succeeded = threading.Event()

    class Server(http.server.ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = False

        def get_request(self):
            sock, address = super().get_request()
            sock.settimeout(8)
            return sock, address

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version, sys_version = "TeleCodeSetup", ""

        def log_message(self, *_args):
            return

        def send(self, status, body=b"", mime="text/plain; charset=utf-8", cookie=None):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.send_header("Connection", "close")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def trusted(self, post=False):
            origin = f"http://{HOST}:{self.server.server_port}"
            if (self.client_address[0] != HOST or self.headers.get("Host", "").lower() != f"{HOST}:{self.server.server_port}" or
                    time.monotonic() - started >= SESSION_SECONDS or finished.is_set()):
                return False
            if post:
                source = self.headers.get("Origin")
                if source is None:
                    source = self.headers.get("Referer", "")
                    try:
                        ref = urllib.parse.urlsplit(source)
                        source = f"{ref.scheme}://{ref.netloc}"
                    except ValueError:
                        return False
                if source != origin:
                    return False
            return True

        def authenticated(self):
            if not self.trusted():
                return False
            cookies = self.headers.get("Cookie", "")
            return any(secrets.compare_digest(part.strip().removeprefix("telecode=").strip('"'), secret)
                       for part in cookies.split(";") if part.strip().startswith("telecode="))

        def do_GET(self):
            nonlocal secret
            if not self.trusted():
                return self.send(403, b"Forbidden")
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/" and not self.authenticated():
                query = urllib.parse.parse_qs(parsed.query, max_num_fields=2)
                if not secrets.compare_digest(query.get("session", [""])[0], secret):
                    return self.send(404, b"Not found")
                # Consume the bearer URL exactly once; the cookie is the only
                # credential used after this redirect.
                secret = secrets.token_urlsafe(32)
                try:
                    body = (WEB / "index.html").read_bytes()
                except OSError:
                    return self.send(503, b"Wizard assets are unavailable")
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Cache-Control", "no-store, private")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
                self.send_header("Set-Cookie", f"telecode={secret}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if not self.authenticated():
                return self.send(403, b"Forbidden")
            assets = {"/": ("index.html", "text/html; charset=utf-8"), "/app.css": ("app.css", "text/css; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8")}
            asset = assets.get(parsed.path)
            if not asset:
                return self.send(404, b"Not found")
            try:
                body = (WEB / asset[0]).read_bytes()
            except OSError:
                return self.send(503, b"Wizard assets are unavailable")
            return self.send(200, body, asset[1])

        def do_POST(self):
            if not self.authenticated() or not self.trusted(post=True):
                return self.send(403, b"Forbidden")
            if self.headers.get_content_type() != "application/json":
                return self.send(415, b"Unsupported media type")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    return self.send(413, b"Invalid request size")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or not secrets.compare_digest(str(data.pop("csrf", "")), csrf):
                    return self.send(403, b"Forbidden")
            except (ValueError, UnicodeDecodeError):
                return self.send(400, b"Invalid request")
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/clients":
                return self.json(200, {"clients": [{"name": h[0], "key": h[1], "detected": bool(setup_cli.discover(h)[0] or setup_cli.discover(h)[1]), "supported": h[3], "config": str(setup_cli.discover(h)[1] or (h[2][0] if h[2] else ""))} for h in setup_cli.HOSTS if h[1]]})
            if path in ("/api/telegram/validate", "/api/telegram/test", "/api/telegram/detect-id"):
                token = str(data.get("token", "")).strip()
                if not TOKEN_RE.fullmatch(token):
                    return self.json(400, {"error": "Invalid token format"})
                try:
                    if path.endswith("validate"):
                        result = _telegram("getMe", token)
                        return self.json(200, {"valid": True, "bot": result.get("username") if isinstance(result, dict) else None})
                    if path.endswith("detect-id"):
                        updates = _telegram("getUpdates", token, {"timeout": 0, "allowed_updates": json.dumps(["message"])}) or []
                        ids = list(dict.fromkeys(str(x["message"]["chat"]["id"]) for x in updates if isinstance(x, dict) and isinstance(x.get("message"), dict) and x["message"].get("chat", {}).get("type") == "private"))
                        return self.json(200, {"chat_ids": ids})
                    chat_id = str(data.get("chat_id", "")).strip()
                    if not re.fullmatch(r"-?\d+", chat_id):
                        return self.json(400, {"error": "Enter a numeric chat ID"})
                    _telegram("sendMessage", token, {"chat_id": chat_id, "text": "TeleCode setup test"})
                    return self.json(200, {"sent": True})
                except (OSError, ValueError, urllib.error.URLError):
                    return self.json(400, {"error": "Telegram request failed; verify credentials and connectivity"})
            if path == "/api/cancel":
                finished.set()
                return self.json(200, {"cancelled": True})
            if path == "/api/apply":
                cli, bot, chat = data.get("cli"), str(data.get("token", "")).strip(), str(data.get("chat_id", "")).strip()
                if data.get("confirm") is not True or not TOKEN_RE.fullmatch(bot) or not re.fullmatch(r"-?\d+", chat):
                    return self.json(400, {"error": "Invalid setup values or missing confirmation"})
                try:
                    config, content = setup_cli.register_for_web(cli)
                    runtime = setup_cli.RUNTIME_CONFIG
                    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
                    runtime.chmod(0o700)
                    credentials = runtime / "telegram.env"
                    if credentials.is_symlink() or (credentials.exists() and credentials.stat().st_uid != os.getuid()):
                        raise PermissionError
                    lines = credentials.read_text().splitlines() if credentials.exists() else []
                    lines = [line for line in lines if not line.startswith(("TG_BOT_TOKEN=", "TG_CHAT_ID="))]
                    setup_cli.backup(config) if config.exists() else None
                    setup_cli.atomic_write(config, content)
                    setup_cli.backup(credentials) if credentials.exists() else None
                    setup_cli.atomic_write(credentials, "\n".join(lines + [f"TG_BOT_TOKEN={bot}", f"TG_CHAT_ID={chat}"]) + "\n")
                    credentials.chmod(0o600)
                except (OSError, ValueError, json.JSONDecodeError):
                    return self.json(500, {"error": "Setup failed; inspect local config and backups before retrying"})
                succeeded.set()
                finished.set()
                return self.json(200, {"ok": True, "message": "Setup complete. Restart the selected CLI to load MCP."})
            return self.send(404, b"Not found")

        def json(self, status, value):
            # Shared CSRF token is returned only after cookie authentication.
            value.setdefault("csrf", csrf)
            return self.send(status, json.dumps(value).encode(), "application/json; charset=utf-8")

        def do_HEAD(self):
            self.send(405, b"Method not allowed")

    try:
        server = Server((HOST, 0), Handler)
    except OSError:
        print("Cannot start local browser setup.")
        return 2
    server.timeout = .5
    url = f"http://{HOST}:{server.server_port}/?session={secret}"
    print(f"Temporary browser setup at http://{HOST}:{server.server_port}/ (expires in 15 minutes).")
    try:
        if not webbrowser.open(url):
            print("Could not open a browser. No files changed.")
            return 2
        while not finished.is_set() and time.monotonic() - started < SESSION_SECONDS:
            server.handle_request()
    except KeyboardInterrupt:
        return 130
    finally:
        finished.set()
        server.server_close()
    return 0 if succeeded.is_set() else 2


if __name__ == "__main__":
    raise SystemExit(run_setup_web())
