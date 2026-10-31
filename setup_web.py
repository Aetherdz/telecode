#!/usr/bin/env python3
"""Temporary, loopback-only browser setup wizard."""
from __future__ import annotations

import http.server
import json
import os
import re
import secrets
import shutil
import subprocess
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


def _safe_error(exc: Exception) -> str:
    """Drop exception details that may embed Telegram URLs/tokens or responses."""
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        return "Telegram request failed; verify connectivity and credentials"
    if isinstance(exc, ValueError):
        return "Telegram rejected the request or returned invalid data"
    return "Telegram request failed"


def _is_installable(cli: str) -> bool:
    host = next((item for item in setup_cli.HOSTS if item[1] == cli), None)
    return bool(host and host[3])


def run_setup_web(*, browser_open=None, serve=True, max_runtime=SESSION_SECONDS, server_factory=None) -> int:
    secret = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(18)
    started, finished = time.monotonic(), threading.Event()
    succeeded = threading.Event()
    last_activity = [started]
    pending_chat = {"id": ""}

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
            nonce_value = nonce if mime.startswith("text/html") else ""
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
            self.send_header("Content-Security-Policy", f"default-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'self' 'nonce-{nonce_value}'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.send_header("Connection", "close")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _csrf_ok(self):
            supplied = self.headers.get("X-CSRF-Token", "")
            return bool(supplied) and secrets.compare_digest(supplied, csrf)

        def trusted(self, post=False):
            origin = f"http://{HOST}:{self.server.server_port}"
            try:
                host = self.headers.get("Host", "")
                parsed_host = urllib.parse.urlsplit("http://" + host)
                valid_authority = (parsed_host.hostname == HOST and parsed_host.port == self.server.server_port and
                                   parsed_host.path == "" and not parsed_host.username and not parsed_host.password)
            except ValueError:
                valid_authority = False
            if (self.client_address[0] != HOST or not valid_authority or
                    time.monotonic() - started >= SESSION_SECONDS or
                    time.monotonic() - last_activity[0] >= SESSION_SECONDS or finished.is_set()):
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
                with self.server.session_lock:
                    if self.server.url_consumed:
                        return self.send(404, b"Not found")
                    self.server.url_consumed = True
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
            if time.monotonic() - last_activity[0] >= SESSION_SECONDS:
                return self.send(403, b"Session expired")
            if self.headers.get("Expect", "").lower() == "100-continue":
                self.send_response_only(417)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.headers.get("Content-Length") is None:
                return self.send(411, b"Content-Length required")
            if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
                return self.send(415, b"Unsupported media type")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    return self.send(413, b"Invalid request size")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or not self._csrf_ok():
                    return self.send(403, b"Forbidden")
            except (ValueError, UnicodeError):
                return self.send(400, b"Invalid request")
            path = urllib.parse.urlsplit(self.path).path
            if path not in {"/api/clients", "/api/state", "/api/browse", "/api/detect", "/api/telegram/validate", "/api/telegram/test", "/api/telegram/detect-id", "/api/cancel", "/api/apply"}:
                    return self.send(404, b"Not found")
            if path == "/api/clients":
                return self.json(200, {"clients": detection.cards()})
            if path == "/api/state":
                agents = detection.cards()
                for agent in agents:
                    agent.update(detection.detect(agent["key"]))
                has_credentials = False
                env_path = setup_cli.RUNTIME_CONFIG / "telegram.env"
                try:
                    if env_path.is_file() and not env_path.is_symlink() and env_path.stat().st_size <= 4096 and (env_path.stat().st_mode & 0o077) == 0:
                        current = env_path.read_text(encoding="utf-8")
                        has_credentials = bool(re.search(r"(?m)^TG_BOT_TOKEN=.{20,}$", current) and
                                               re.search(r"(?m)^TG_CHAT_ID=-?\d+$", current))
                except OSError:
                    pass
                available = False
                if os.name == "posix" and shutil.which("systemctl"):
                    try:
                        available = subprocess.run(["systemctl", "--user", "show-environment"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False).returncode == 0
                    except (OSError, subprocess.TimeoutExpired):
                        available = False
                config_paths = {key: str(next((p for h in setup_cli.HOSTS if h[1] == key for p in h[2]), "")) for key in ("opencode", "claude", "codex", "cursor", "gemini", "cline", "roo", "q")}
                return self.json(200, {"agents": agents, "service": {"mode": "systemd user service" if available else "foreground", "systemd": available}, "files": [str(setup_cli.RUNTIME_CONFIG / "telegram.env"), "selected client MCP configuration"], "config_paths": config_paths, "has_credentials": has_credentials})
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
                        pending_chat["id"] = ""
                        return self.json(200, {"ok": True, "valid": True, "bot": {"name": result.get("first_name", ""), "username": result.get("username", "") } if isinstance(result, dict) else {}})
                    if path.endswith("detect-id"):
                        chats = _detect_chats(token)
                        chat_id = chats[0] if chats else ""
                        if chat_id:
                            _telegram("getMe", token)
                        pending_chat["id"] = chat_id
                        return self.json(200, {"ok": bool(chat_id), "pending": not bool(chat_id), "chat_id_masked": detection.mask_chat_id(chat_id) if chat_id else ""})
                    chat_id = str(data.get("chat_id", "")).strip()
                    if data.get("use_detected"):
                        chat_id = pending_chat["id"]
                    if not re.fullmatch(r"-?\d+", chat_id):
                        return self.json(400, {"error": "Enter a numeric chat ID"})
                    _telegram("sendMessage", token, {"chat_id": chat_id, "text": "TeleCode setup test"})
                    return self.json(200, {"ok": True, "sent": True, "message": "Test message sent"})
                except (OSError, ValueError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                    return self.json(400, {"error": _safe_error(exc)})
            if path == "/api/cancel":
                finished.set()
                self.send(200, b'{"cancelled":true}', "application/json; charset=utf-8")
                return
            if path == "/api/apply":
                if data.get("use_detected") and data.get("chat_id"):
                    return self.json(400, {"error": "Provide either a detected chat or a manual ID, not both"})
                cli, bot, chat = data.get("cli") or data.get("agent"), str(data.get("token", "")).strip(), str(data.get("chat_id", "")).strip()
                if cli == "manual":
                    if data.get("confirm") is not True or not TOKEN_RE.fullmatch(bot) or not re.fullmatch(r"-?\d+", pending_chat["id"] if data.get("use_detected") else chat):
                        return self.json(400, {"error": "Confirm valid Telegram credentials"})
                    return self.json(400, {"error": "Manual MCP clients are not modified automatically. Use the terminal instructions."})
                if not _is_installable(cli):
                    return self.json(400, {"error": "Choose a supported client"})
                if data.get("use_detected"):
                    chat = pending_chat["id"]
                elif pending_chat["id"]:
                    pending_chat["id"] = ""
                if data.get("confirm") is not True or not TOKEN_RE.fullmatch(bot) or not re.fullmatch(r"-?\d+", chat):
                    return self.json(400, {"error": "Invalid setup values or missing confirmation"})
                try:
                    config, content = setup_cli.register_for_web(cli)
                    allowed = {p.resolve() for host in setup_cli.HOSTS if host[1] == cli for p in host[2]}
                    if config.resolve() not in allowed or config.is_symlink():
                        raise ValueError("Unknown or unsafe config destination")
                    for host in setup_cli.HOSTS:
                        if host[1] != cli:
                            continue
                        for candidate in host[2]:
                            if candidate.resolve() == config.resolve():
                                config = candidate
                                break
                    config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    if not config.parent.resolve().is_relative_to(Path.home().resolve()):
                        raise PermissionError("config parent outside home")
                    if config.parent.stat().st_uid != os.getuid():
                        raise PermissionError("config parent is not owned by this user")
                    if config.parent != config.parent.resolve():
                        raise PermissionError("symlinked config path is not permitted")
                    parent = config.parent
                    while parent != Path.home().resolve().parent:
                        if parent.is_symlink():
                            raise PermissionError("symlinked config ancestor is not permitted")
                        parent = parent.parent
                    runtime = setup_cli.RUNTIME_CONFIG
                    if runtime.is_symlink():
                        raise PermissionError("config directory must not be a symlink")
                    if not runtime.resolve().is_relative_to(Path.home().resolve()):
                        raise PermissionError("config path outside home")
                    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
                    if runtime.stat().st_uid != os.getuid():
                        raise PermissionError("config directory is not owned by this user")
                    runtime.chmod(0o700)
                    credentials = runtime / "telegram.env"
                    if credentials.is_symlink() or (credentials.exists() and credentials.stat().st_mode & 0o077):
                        raise PermissionError
                    if credentials.exists() and hasattr(os, "getuid") and credentials.stat().st_uid != os.getuid():
                        raise PermissionError
                    if credentials.exists() and not credentials.is_file():
                        raise PermissionError("credential path is not a regular file")
                    if credentials.exists() and credentials.stat().st_size > 4096:
                        raise PermissionError("credential file is unexpectedly large")
                    if config.exists() and (config.is_symlink() or config.resolve() != config.absolute()):
                        raise PermissionError("client config path is symlinked")
                    if config.exists() and config.stat().st_uid != os.getuid():
                        raise PermissionError("client config is not owned by this user")
                    setup_cli.backup(config) if config.exists() else None
                    setup_cli.atomic_write(config, content)
                    try:
                        lines = credentials.read_text().splitlines() if credentials.exists() else []
                        lines = [line for line in lines if not line.startswith(("TG_BOT_TOKEN=", "TG_CHAT_ID="))]
                        setup_cli.backup(credentials) if credentials.exists() else None
                        setup_cli.atomic_write(credentials, "\n".join(lines + [f"TG_BOT_TOKEN={bot}", f"TG_CHAT_ID={chat}"]) + "\n", mode=0o600)
                    except OSError:
                        if config.exists():
                            try:
                                backup = next(config.parent.glob(config.name + ".telegram-bridge.bak.*"), None)
                                if backup is not None:
                                    setup_cli.atomic_write(config, backup.read_text(encoding="utf-8"))
                                else:
                                    config.unlink()
                            except OSError:
                                pass
                        raise
                    service_mode = "foreground"
                    if os.name == "posix" and shutil.which("systemctl"):
                        try:
                            available = subprocess.run(
                                ["systemctl", "--user", "show-environment"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                timeout=3, check=False,
                            ).returncode == 0
                        except (OSError, subprocess.TimeoutExpired):
                            available = False
                        if available:
                            service_mode = "systemd user service"
                            service_template = (Path(__file__).resolve().parent / "telegram-bridge.service").read_text(encoding="utf-8")
                            service_path = Path.home() / ".config/systemd/user/telecode.service"
                            service_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                            setup_cli.atomic_write(service_path, service_template.replace("%h", str(Path.home())), mode=0o600)
                            subprocess.run(["systemctl", "--user", "daemon-reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
                            subprocess.run(["systemctl", "--user", "enable", "--now", "telecode.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, check=False)
                        else:
                            print("Run `telecode listen` to start the listener.")
                except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
                    return self.json(500, {"error": "Setup failed; inspect local config and backups before retrying"})
                succeeded.set()
                response = self.json(200, {"ok": True, "message": "Setup complete. Restart the selected CLI to load MCP.", "steps": [{"label": "Register MCP client", "status": "done"}, {"label": "Write private credentials", "status": "done"}, {"label": "Enable service or use foreground", "status": "done"}], "summary": {"agent": str(cli), "sessions": int(data.get("session_count", 0) or 0), "bot": "connected", "chat_id": detection.mask_chat_id(chat), "service": service_mode, "files": [str(config), str(credentials)]}})
                finished.set()
                return response
            return self.send(404, b"Not found")

        def json(self, status, value):
            # Shared CSRF token is returned only after cookie authentication.
            if self.authenticated():
                value.setdefault("csrf", csrf)
            return self.send(status, json.dumps(value).encode(), "application/json; charset=utf-8")

        def do_HEAD(self):
            self.send(405, b"Method not allowed")

    try:
        factory = server_factory or Server
        server = factory((HOST, 0), Handler)
    except OSError:
        print("Cannot start local browser setup.")
        return 2
    server.timeout = .5
    server.session_secret = secret
    server.url_consumed = False
    server.session_lock = threading.Lock()
    url = f"http://{HOST}:{server.server_port}/?session={secret}"
    if not serve:
        server.server_close()
        return 0
    print(f"Temporary browser setup at http://{HOST}:{server.server_port}/ (expires in 15 minutes).")
    print("If no browser opens, forward the local port with: ssh -L " + str(server.server_port) + ":127.0.0.1:" + str(server.server_port) + " <host>")
    try:
        (browser_open or webbrowser.open)(url)
        while not finished.is_set() and time.monotonic() - last_activity[0] < max_runtime:
            server.handle_request()
    except KeyboardInterrupt:
        return 130
    finally:
        finished.set()
        server.server_close()
    return 0 if succeeded.is_set() else 2


if __name__ == "__main__":
    raise SystemExit(run_setup_web())
