#!/usr/bin/env python3
"""Temporary, loopback-only browser setup wizard."""
from __future__ import annotations

import http.server
import json
import os
import re
import secrets
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

import setup_cli
from telegram_bridge import detection

HOST = "127.0.0.1"
SESSION_SECONDS = 15 * 60
MAX_BODY = 32 * 1024
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


def _detect_chats(token: str, *, attempts: int = 5, interval: float = 1.0):
    """Poll our own bot briefly for private chats; never wait on Telegram long-poll."""
    found = {}
    for attempt in range(attempts):
        updates = _telegram("getUpdates", token, {"timeout": 0, "allowed_updates": json.dumps(["message"])}) or []
        if isinstance(updates, list):
            for update in updates:
                if not isinstance(update, dict):
                    continue
                message = update.get("message")
                chat = message.get("chat") if isinstance(message, dict) else None
                if isinstance(chat, dict) and chat.get("type") == "private" and chat.get("id") is not None:
                    found[str(chat["id"])] = True
        if found or attempt + 1 == attempts:
            break
        time.sleep(interval)
    return list(found)


def run_setup_web(*, browser_open=None, serve=True) -> int:
    secret = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(18)
    started, finished = time.monotonic(), threading.Event()
    succeeded = threading.Event()
    last_activity = [started]

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
            self.nonce = nonce
            if mime.startswith("text/html"):
                body = body.decode("utf-8").replace("{{NONCE}}", nonce).replace("{{CSRF}}", csrf).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", f"default-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'self' 'nonce-{nonce}'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.send_header("Connection", "close")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _csrf_ok(self):
            supplied = self.headers.get("X-CSRF-Token", "")
            return secrets.compare_digest(supplied, csrf)

        def trusted(self, post=False):
            origin = f"http://{HOST}:{self.server.server_port}"
            if (self.client_address[0] != HOST or self.headers.get("Host", "").lower() != f"{HOST}:{self.server.server_port}" or
                    time.monotonic() - started >= SESSION_SECONDS or finished.is_set()):
                return False
            last_activity[0] = time.monotonic()
            if post:
                source = self.headers.get("Origin") or ""
                referer = self.headers.get("Referer", "")
                try:
                    ref = urllib.parse.urlsplit(referer)
                    ref_origin = f"{ref.scheme}://{ref.netloc}" if ref.scheme and ref.netloc else ""
                except ValueError:
                    return False
                if (source and source != origin) or (referer and ref_origin != origin) or (not source and not referer):
                    return False
            return True

        def authenticated(self, post=False):
            if not self.trusted(post=post):
                return False
            cookies = self.headers.get("Cookie", "")
            supplied = next((part.split("=", 1)[1].strip().strip('"') for part in cookies.split(";")
                             if part.strip().startswith("telecode=") and "=" in part), "")
            return secrets.compare_digest(supplied, self.server.session_secret)

        def _page_error(self, code=400):
            return self.send(code, b"Request rejected")

        def json(self, status, value):
            value.setdefault("csrf", csrf)
            return self.send(status, json.dumps(value).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            if not self.trusted():
                return self.send(403, b"Forbidden")
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/" and not self.authenticated():
                query = urllib.parse.parse_qs(parsed.query, max_num_fields=2)
                if not secrets.compare_digest(query.get("session", [""])[0], secret):
                    return self.send(404, b"Not found")
                # Consume the bearer URL exactly once; the cookie is the only
                # credential used after this redirect.
                self.server.session_secret = secrets.token_urlsafe(32)
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Cache-Control", "no-store, private")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Set-Cookie", f"telecode={self.server.session_secret}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}")
                self.send_header("Content-Security-Policy", "default-src 'none'; base-uri 'none'; frame-ancestors 'none'")
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
            if not self.authenticated(post=True):
                return self.send(403, b"Forbidden")
            if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
                return self.send(415, b"Unsupported media type")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    return self.send(413, b"Invalid request size")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or not self._csrf_ok():
                    return self.send(403, b"Forbidden")
            except (ValueError, UnicodeDecodeError):
                return self.send(400, b"Invalid request")
            path = urllib.parse.urlsplit(self.path).path
            if path not in {"/api/clients", "/api/state", "/api/browse", "/api/detect", "/api/telegram/validate", "/api/telegram/test", "/api/telegram/detect-id", "/api/cancel", "/api/apply"}:
                return self.send(404, b"Not found")
            if path == "/api/clients":
                return self.json(200, {"clients": detection.clients(setup_cli)})
            if path == "/api/state":
                agents = detection.cards()
                for agent in agents:
                    agent.update(detection.detect(agent["key"]))
                return self.json(200, {"agents": agents, "service": {"mode": "systemd user service" if os.name == "posix" and shutil.which("systemctl") else "foreground", "systemd": bool(os.name == "posix" and shutil.which("systemctl"))}, "files": [str(setup_cli.RUNTIME_CONFIG / "telegram.env"), "selected client MCP configuration"], "has_credentials": False})
            if path == "/api/browse":
                requested = data.get("path") or str(Path.home())
                if requested != str(Path.home()) and data.get("agent") not in {"opencode", "claude", "codex", "cursor", "gemini", "cline", "roo", "q", "manual"}:
                    return self.json(400, {"error": "Choose an agent before browsing folders"})
                try:
                    entries = detection.browse(requested)
                except (ValueError, OSError):
                    return self.json(400, {"error": "Folder is outside the home directory or unavailable"})
                return self.json(200, entries)
            if path == "/api/detect":
                agent = data.get("agent") or data.get("cli")
                try:
                    result = detection.detect(agent, data.get("path"))
                except (ValueError, OSError):
                    return self.json(400, {"ok": False, "needs_path": True, "error": "Unsupported or unsafe session folder"})
                return self.json(200, result)
            if path in ("/api/telegram/validate", "/api/telegram/test", "/api/telegram/detect-id"):
                token = str(data.get("token", "")).strip()
                if not TOKEN_RE.fullmatch(token):
                    return self.json(400, {"error": "Invalid token format"})
                try:
                    if path.endswith("validate"):
                        result = _telegram("getMe", token)
                        return self.json(200, {"ok": True, "valid": True, "bot": {"name": result.get("first_name", ""), "username": result.get("username", "") } if isinstance(result, dict) else {}})
                    if path.endswith("detect-id"):
                        chats = _detect_chats(token)
                        chat_id = chats[0] if chats else ""
                        self.server.pending_chat_id = chat_id
                        return self.json(200, {"ok": bool(chat_id), "pending": not bool(chat_id), "chat_id_masked": detection.mask_chat_id(chat_id) if chat_id else ""})
                    chat_id = str(data.get("chat_id", "")).strip()
                    if data.get("use_detected"):
                        chat_id = getattr(self.server, "pending_chat_id", "")
                    if not re.fullmatch(r"-?\d+", chat_id):
                        return self.json(400, {"error": "Enter a numeric chat ID"})
                    _telegram("sendMessage", token, {"chat_id": chat_id, "text": "TeleCode setup test"})
                    return self.json(200, {"ok": True, "sent": True, "message": "Test message sent"})
                except (OSError, ValueError, urllib.error.URLError):
                    return self.json(400, {"error": "Telegram request failed; verify credentials and connectivity"})
            if path == "/api/cancel":
                finished.set()
                return self.json(200, {"cancelled": True})
            if path == "/api/apply":
                cli, bot, chat = data.get("cli") or data.get("agent"), str(data.get("token", "")).strip(), str(data.get("chat_id", "")).strip()
                if data.get("use_detected"):
                    chat = getattr(self.server, "pending_chat_id", "")
                if data.get("confirm") is not True or not TOKEN_RE.fullmatch(bot) or not re.fullmatch(r"-?\d+", chat):
                    return self.json(400, {"error": "Invalid setup values or missing confirmation"})
                try:
                    config, content = setup_cli.register_for_web(cli)
                    allowed = {p.resolve() for host in setup_cli.HOSTS if host[1] == cli for p in host[2]}
                    if config.resolve() not in allowed or config.is_symlink():
                        raise ValueError("Unknown or unsafe config destination")
                    runtime = setup_cli.RUNTIME_CONFIG
                    if runtime.is_symlink():
                        raise PermissionError("config directory must not be a symlink")
                    if not runtime.resolve().is_relative_to(Path.home().resolve()):
                        raise PermissionError("config path outside home")
                    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
                    runtime.chmod(0o700)
                    credentials = runtime / "telegram.env"
                    if credentials.is_symlink() or (credentials.exists() and credentials.stat().st_mode & 0o077):
                        raise PermissionError
                    if credentials.exists() and hasattr(os, "getuid") and credentials.stat().st_uid != os.getuid():
                        raise PermissionError
                    lines = credentials.read_text().splitlines() if credentials.exists() else []
                    lines = [line for line in lines if not line.startswith(("TG_BOT_TOKEN=", "TG_CHAT_ID="))]
                    setup_cli.backup(config) if config.exists() else None
                    setup_cli.atomic_write(config, content)
                    setup_cli.backup(credentials) if credentials.exists() else None
                    setup_cli.atomic_write(credentials, "\n".join(lines + [f"TG_BOT_TOKEN={bot}", f"TG_CHAT_ID={chat}"]) + "\n", mode=0o600)
                except (OSError, ValueError, json.JSONDecodeError):
                    return self.json(500, {"error": "Setup failed; inspect local config and backups before retrying"})
                succeeded.set()
                response = self.json(200, {"ok": True, "message": "Setup complete. Restart the selected CLI to load MCP.", "steps": [{"label": "Register MCP client", "status": "done"}, {"label": "Write private credentials", "status": "done"}, {"label": "Enable service or use foreground", "status": "done"}], "summary": {"agent": str(cli), "sessions": 0, "bot": "connected", "chat_id": detection.mask_chat_id(chat), "service": "systemd user service" if shutil.which("systemctl") else "foreground"}})
                finished.set()
                return response
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
    server.session_secret = secret
    url = f"http://{HOST}:{server.server_port}/?session={secret}"
    if not serve:
        server.server_close()
        return 0
    print(f"Temporary browser setup at http://{HOST}:{server.server_port}/ (expires in 15 minutes).")
    print("If no browser opens, forward the local port with: ssh -L " + str(server.server_port) + ":127.0.0.1:" + str(server.server_port) + " <host>")
    try:
        (browser_open or webbrowser.open)(url)
        while not finished.is_set() and time.monotonic() - last_activity[0] < SESSION_SECONDS:
            server.handle_request()
    except KeyboardInterrupt:
        return 130
    finally:
        finished.set()
        server.server_close()
    return 0 if succeeded.is_set() else 2


if __name__ == "__main__":
    raise SystemExit(run_setup_web())
