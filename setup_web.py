#!/usr/bin/env python3
"""Temporary loopback-only browser setup wizard for TeleCode."""
from __future__ import annotations

import html
import http.server
import json
import re
import secrets
import threading
import time
import urllib.parse
import webbrowser

import setup_cli

HOST = "127.0.0.1"
SESSION_SECONDS = 15 * 60
MAX_BODY = 16 * 1024
MAX_REQUESTS = 150


def _page(token: str, clients: list[dict]) -> bytes:
    data = html.escape(json.dumps(clients, ensure_ascii=False), quote=False)
    csrf = html.escape(token, quote=True)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>TeleCode local setup</title>
<style>
:root{{--bg:#f5f2ec;--ink:#24221e;--muted:#68635b;--line:#d9d2c8;--accent:#a94931;--card:#fff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,sans-serif}}
main{{max-width:780px;margin:5vh auto;padding:24px}}header{{display:flex;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:18px}}
.brand{{font-weight:800;letter-spacing:.04em}}.eyebrow{{color:var(--accent);font-size:.75rem;letter-spacing:.16em;font-weight:700;margin-top:38px}}
h1{{font-size:clamp(2rem,7vw,3.6rem);line-height:1.03;letter-spacing:-.05em;max-width:14ch}}h2{{font-size:1.6rem;line-height:1.15}}.muted{{color:var(--muted)}}
.steps{{display:flex;gap:8px;margin:28px 0}}.step{{flex:1;border-top:3px solid var(--line);padding-top:8px;color:var(--muted)}}.step.active{{border-color:var(--accent);color:var(--ink)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:clamp(20px,5vw,36px);box-shadow:0 12px 32px #2520150b}}
.option{{display:flex;gap:12px;padding:14px;border:1px solid var(--line);border-radius:8px;margin:10px 0;cursor:pointer}}.option:has(input:checked){{border-color:var(--accent);background:#fbf5f1}}input,button{{font:inherit}}input[type=password],input[type=text]{{width:100%;padding:12px;border:1px solid var(--line);border-radius:7px;background:white;color:var(--ink)}}label.field{{display:block;font-weight:650;margin:18px 0 7px}}.help{{font-size:.9rem;color:var(--muted)}}
.notice{{padding:12px;background:#f4eee3;border-radius:7px;color:#51483a;margin-top:16px}}.error{{color:#9b2e20;min-height:1.4em}}.summary{{display:grid;grid-template-columns:minmax(120px, .7fr) 1.5fr;gap:10px;padding:16px 0}}.summary b{{font-weight:650}}.actions{{display:flex;justify-content:space-between;gap:12px;margin-top:24px}}button{{border:0;border-radius:7px;padding:12px 18px;background:var(--accent);color:white;font-weight:700;cursor:pointer}}button.secondary{{background:transparent;color:var(--ink);border:1px solid var(--line)}}button:focus-visible,input:focus-visible,.option:focus-within{{outline:3px solid #39709b;outline-offset:3px}}.hidden{{display:none!important}}footer{{color:var(--muted);font-size:.85rem;margin-top:18px}}
@media(max-width:560px){{main{{margin:0 auto;padding:18px}}.summary{{grid-template-columns:1fr;gap:3px}}.actions button{{flex:1}}.steps{{font-size:.78rem}}}}
</style></head><body><main><header><span class="brand">&gt;_ TeleCode</span><span class="muted">Temporary local setup</span></header>
<p class="eyebrow">LOCAL SETUP / PRIVATE BY DESIGN</p><h1>Connect your coding workspace.</h1><p class="muted">Three steps. Nothing changes until you review and confirm.</p>
<div class="steps"><div class="step active" data-label="1">01 &nbsp; Coding CLI</div><div class="step" data-label="2">02 &nbsp; Telegram</div><div class="step" data-label="3">03 &nbsp; Review</div></div>
<form id="wizard"><input type="hidden" name="csrf" value="{csrf}">
<section class="card panel" data-step="1"><h2>Choose a coding CLI</h2><p class="muted">Select a client for MCP tools. Session discovery is not performed during setup.</p><div id="clients">{data}</div><p class="help">OpenCode supports targeted routing. Other clients provide outbound MCP tools where supported.</p><p class="error" id="error-1" role="alert"></p><div class="actions"><span></span><button type="button" data-next>Continue</button></div></section>
<section class="card panel hidden" data-step="2"><h2>Connect Telegram</h2><p class="muted">Credentials are saved only in private local configuration. The wizard does not contact Telegram.</p>
<label class="field" for="token">Bot token</label><input id="token" name="token" type="password" autocomplete="new-password" required>
<label class="field" for="chat_id">Owner chat ID</label><input id="chat_id" name="chat_id" type="text" inputmode="numeric" autocomplete="off" required>
<p class="notice">Get a token from @BotFather. Find your numeric ID with @Getmyid_bot; never give that bot your token.</p><p class="error" id="error-2" role="alert"></p>
<div class="actions"><button class="secondary" type="button" data-back>Back</button><button type="button" data-next>Continue</button></div></section>
<section class="card panel hidden" data-step="3"><h2>Review and confirm</h2><p class="muted">The selected client configuration will be updated and Telegram credentials saved privately.</p>
<div class="summary"><b>Coding CLI</b><span id="review-cli"></span><b>Configuration</b><span id="review-path"></span><b>Telegram credentials</b><span>Token and chat ID (hidden)</span></div>
<label><input type="checkbox" name="confirm" required> I authorize these local configuration changes.</label><p class="notice">An existing config is backed up before it is updated. Cancel leaves files unchanged.</p><p class="error" id="error-3" role="alert"></p>
<div class="actions"><button class="secondary" type="button" data-back>Back</button><button type="button" id="cancel" class="secondary">Cancel setup</button><button type="submit" id="apply">Confirm &amp; apply</button></div></section></form>
<section id="result" class="card hidden" aria-live="polite"></section><footer>This local server expires after 15 minutes. Closing the browser does not cancel it; use Cancel setup or stop the terminal process.</footer></main>
<script nonce="{csrf}">
const clients=JSON.parse(document.querySelector('#clients').textContent), list=document.querySelector('#clients');list.textContent='';
for(const c of clients){{const label=document.createElement('label');label.className='option';const radio=document.createElement('input');radio.type='radio';radio.name='cli';radio.value=c.key;radio.required=true;radio.dataset.path=c.config||c.paths[0];const text=document.createElement('span');text.textContent=c.name+' — '+(c.detected?'detected':'not detected')+(c.supported?'':' (manual config only)');label.append(radio,text);list.append(label);if(c.key==='opencode'&&c.detected)radio.checked=true}}
let current=1;function go(n){{current=n;document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('hidden',Number(p.dataset.step)!==n));document.querySelectorAll('.step').forEach((s,i)=>s.classList.toggle('active',i===n-1));window.scrollTo(0,0)}}
document.querySelectorAll('[data-next]').forEach(b=>b.addEventListener('click',()=>{{const err=document.querySelector('#error-'+current);err.textContent='';if(current===1&&!document.querySelector('[name=cli]:checked')){{err.textContent='Select a supported CLI to continue.';return}}if(current===2){{if(!/^\\d{{5,}}:[A-Za-z0-9_-]{{20,}}$/.test(document.querySelector('#token').value.trim())){{err.textContent='Enter a valid-looking bot token.';return}}if(!/^-?[0-9]+$/.test(document.querySelector('#chat_id').value.trim())){{err.textContent='Enter a numeric chat ID.';return}}}}if(current===1){{const selected=document.querySelector('[name=cli]:checked');document.querySelector('#review-cli').textContent=selected.parentElement.innerText;document.querySelector('#review-path').textContent=selected.dataset.path||'Standard client configuration'}}go(current+1)}}));
document.querySelectorAll('[data-back]').forEach(b=>b.addEventListener('click',()=>go(current-1)));
document.querySelector('#cancel').addEventListener('click',async()=>{{await fetch('/cancel',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:new URLSearchParams({{csrf:document.querySelector('[name=csrf]').value}})}});document.querySelector('#wizard').classList.add('hidden');const result=document.querySelector('#result');result.classList.remove('hidden');result.textContent='Setup cancelled. No changes were made.'}});
document.querySelector('#wizard').addEventListener('submit',async e=>{{e.preventDefault();if(!document.querySelector('[name=confirm]').checked)return;const button=document.querySelector('#apply');button.disabled=true;try{{const response=await fetch('/apply',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:new URLSearchParams(new FormData(e.currentTarget))}});const message=await response.text();if(response.ok){{document.querySelector('#wizard').classList.add('hidden');const result=document.querySelector('#result');result.classList.remove('hidden');result.innerHTML='<h2>Setup complete</h2><p></p>';result.querySelector('p').textContent=message}}else document.querySelector('#error-3').textContent=message}}catch(_){{document.querySelector('#error-3').textContent='The local setup request failed. No success was reported.'}}finally{{button.disabled=false}}}});
</script></body></html>'''.encode("utf-8")


def _clients():
    clients = []
    for host in setup_cli.HOSTS:
        if host[1] is None:
            continue
        found_cli, config, supported = setup_cli.discover(host)
        clients.append({"name": host[0], "key": host[1], "detected": bool(found_cli or config),
                        "supported": supported, "config": str(config) if config else "",
                        "paths": [str(path) for path in host[2]]})
    return clients


def run_setup_web() -> int:
    finished = threading.Event()
    token = secrets.token_urlsafe(32)
    started = time.monotonic()

    class Server(http.server.ThreadingHTTPServer):
        allow_reuse_address = False
        daemon_threads = True
        request_queue_size = 8

        def get_request(self):
            sock, address = super().get_request()
            sock.settimeout(10)
            return sock, address

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "LocalSetup"
        sys_version = ""
        timeout = 10

        def log_message(self, fmt, *args):
            return

        def _secure(self):
            return (self.client_address[0] == HOST and
                    self.headers.get("Host", "").lower() == f"{HOST}:{self.server.server_port}" and
                    time.monotonic() - started < SESSION_SECONDS and not finished.is_set())

        def _send(self, status, body=b"", content_type="text/plain; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", f"default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-{token}'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("Connection", "close")
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):
            if not self._secure():
                self._send(403, b"Forbidden")
                return
            parsed = urllib.parse.urlsplit(self.path)
            try:
                query = urllib.parse.parse_qs(parsed.query, max_num_fields=2)
            except ValueError:
                self._send(400, b"Bad request")
                return
            if parsed.path != "/" or not secrets.compare_digest(query.get("session", [""])[0], token):
                self._send(404, b"Not found")
                return
            self._send(200, _page(token, _clients()), "text/html; charset=utf-8")

        def do_POST(self):
            if not self._secure() or self.headers.get("Origin") != f"http://{HOST}:{self.server.server_port}":
                self._send(403, b"Forbidden")
                return
            if self.headers.get_content_type() != "application/x-www-form-urlencoded":
                self._send(415, b"Unsupported media type")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    self._send(413, b"Invalid request size")
                    return
                fields = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "strict"), max_num_fields=12)
            except (ValueError, UnicodeDecodeError):
                self._send(400, b"Invalid request")
                return
            if not secrets.compare_digest(fields.get("csrf", [""])[0], token):
                self._send(403, b"Forbidden")
                return
            if self.path == "/cancel":
                self._send(200, b"Cancelled")
                finished.set()
                return
            if self.path != "/apply":
                self._send(404, b"Not found")
                return
            if any(len(values) != 1 for values in fields.values()):
                self._send(400, b"Fields must appear once")
                return
            cli = fields.get("cli", [""])[0]
            bot_token = fields.get("token", [""])[0].strip()
            chat_id = fields.get("chat_id", [""])[0].strip()
            if fields.get("confirm", [""])[0] != "on" or not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{20,}", bot_token) or not re.fullmatch(r"-?[0-9]+", chat_id):
                self._send(400, b"Invalid setup values or missing confirmation")
                return
            try:
                config, contents = setup_cli.register_for_web(cli)
                config.parent.mkdir(parents=True, exist_ok=True)
                config_backup = setup_cli.backup(config) if config.exists() else None
                setup_cli.atomic_write(config, contents)
                runtime = setup_cli.RUNTIME_CONFIG
                runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
                runtime.chmod(0o700)
                credentials = runtime / "telegram.env"
                if credentials.is_symlink():
                    raise PermissionError("telegram.env must not be a symlink")
                if credentials.exists():
                    meta = credentials.stat()
                    if hasattr(meta, "st_uid") and meta.st_uid != __import__("os").getuid():
                        raise PermissionError("telegram.env must be owned by the current user")
                    if meta.st_mode & 0o077:
                        raise PermissionError("telegram.env permissions must be 0600")
                lines = credentials.read_text(encoding="utf-8").splitlines() if credentials.exists() else []
                lines = [line for line in lines if not line.startswith(("TG_BOT_TOKEN=", "TG_CHAT_ID="))]
                lines.extend((f"TG_BOT_TOKEN={bot_token}", f"TG_CHAT_ID={chat_id}"))
                credential_backup = setup_cli.backup(credentials) if credentials.exists() else None
                setup_cli.atomic_write(credentials, "\n".join(lines) + "\n")
                credentials.chmod(0o600)
            except (OSError, ValueError, json.JSONDecodeError):
                # Do not expose filesystem paths or exception text to the browser.
                self._send(500, b"Setup failed. Inspect local config and backups before retrying.")
                return
            self._send(200, b"Credentials saved privately. Restart the selected CLI to load MCP.")
            finished.set()

        def do_HEAD(self):
            self._send(405, b"Method not allowed")

    try:
        server = Server((HOST, 0), Handler)
    except OSError as exc:
        print(f"Cannot start local browser setup: {exc}")
        return 2
    server.timeout = 0.5
    print(f"Temporary browser setup at http://{HOST}:{server.server_port}/ (expires in 15 minutes).")
    print("Opening a one-time local link in your browser; do not share it.")
    url = f"http://{HOST}:{server.server_port}/?session={token}"
    try:
        if not webbrowser.open(url):
            print("Could not open a browser. No files changed.")
            return 2
        requests = 0
        while not finished.is_set() and time.monotonic() - started < SESSION_SECONDS and requests < MAX_REQUESTS:
            server.handle_request()
            requests += 1
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        return 130
    finally:
        finished.set()
        server.server_close()
    return 0 if getattr(server, "setup_succeeded", False) else 2


if __name__ == "__main__":
    raise SystemExit(run_setup_web())
