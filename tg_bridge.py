#!/usr/bin/env python3
"""
Telegram bridge for the arsenal agent — relay + session wake (no LLM routing).

Owner messages are stored in inbox.jsonl AND injected into the live OpenCode
session so a new Telegram message starts (or steers) an agent turn immediately.
Non-owner messages are never injected.

Session targeting: auto-discovery of the newest root session for this home
directory; OPENCODE_SESSION_ID is a fallback pin (OPENCODE_SESSION_MODE=pin
forces pin-only). Delivery: TG_DELIVERY=steer (default; runs at the next step
boundary, even while the session is busy) or queue (waits for turn end).

Commands:
  listen        daemon: long-polls getUpdates, stores OWNER messages to
                inbox.jsonl and injects them into the live OpenCode session
  read          print unread messages (advances cursor)
  wait SECONDS  block until an unread message arrives or timeout
  send TEXT     send a message to the owner chat (text may also come via stdin)
  sendfile PATH [CAPTION]   send a document to the owner chat
  status        bot identity, unread count, listener state, inject target

Security:
  - Only messages from TG_CHAT_ID are accepted; everything else is ignored.
  - Config lives in telegram.env (chmod 600).
  - Injection can be disabled with OPENCODE_INJECT=0 in telegram.env.
"""
import json
import os
import pathlib
import queue
import re
import secrets
import stat
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request

BASE = pathlib.Path(os.environ.get(
    "TELEGRAM_BRIDGE_HOME", str(pathlib.Path(os.environ.get("XDG_CONFIG_HOME", pathlib.Path.home() / ".config")) / "telegram-bridge")
)).expanduser().resolve()
ENV = BASE / "telegram.env"
INBOX = BASE / "inbox.jsonl"
OFFSET = BASE / "offset.txt"
CURSOR = BASE / "cursor.txt"
PID = BASE / "listener.pid"
FILES = BASE / "files"
STATE = BASE / "wake-session.txt"
ACTIVE_SESSION = BASE / "active-session.json"
MODELS_CACHE = BASE / "models-cache.json"
INJECT_Q: "queue.Queue[dict]" = queue.Queue()
SESSION_PAGE_SIZE = 8
MODELS_PAGE_SIZE = 8
SESSION_PAGE = 0
os.umask(0o077)


def ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(msg, **kwargs):
    """Diagnostics go to stderr (stdout stays clean for command output / MCP)."""
    kwargs.pop("flush", None)
    print(msg, file=sys.stderr, flush=True, **kwargs)


def load_env():
    cfg = {}
    if not ENV.is_file():
        raise FileNotFoundError(f"missing private Telegram config: {ENV}")
    if ENV.is_symlink():
        raise PermissionError("telegram.env must not be a symlink")
    metadata = ENV.stat()
    if metadata.st_mode & 0o077:
        raise PermissionError("telegram.env permissions must be 0600")
    if os.name != "nt" and metadata.st_uid != os.getuid():
        raise PermissionError("telegram.env must be owned by the current user")
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip().strip('"').strip("'")
    if not cfg.get("TG_BOT_TOKEN") or not cfg.get("TG_CHAT_ID"):
        raise ValueError("telegram.env must define TG_BOT_TOKEN and TG_CHAT_ID")
    return cfg


def api(token, method, params=None, timeout=60):
    params = dict(params or {})
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _download_file(token, file_id, name, destination=None):
    """Fetch a Telegram document/photo into the selected session folder."""
    try:
        fr = api(token, "getFile", {"file_id": file_id}, timeout=60)
        fp = (fr.get("result") or {}).get("file_path")
        if not fp:
            return ""
        destination = destination or FILES
        destination.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if (c.isalnum() or c in "._- ()[]") else "_" for c in name)[:120] or "file"
        dest = destination / f"{int(time.time() * 1000)}_{os.getpid()}_{safe}"
        url = f"https://api.telegram.org/file/bot{token}/{fp}"
        with urllib.request.urlopen(url, timeout=180) as r, open(dest, "xb") as f:
            size = 0
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > 20 * 1024 * 1024:
                    raise ValueError("incoming file exceeds Telegram bot download limit")
                f.write(chunk)
        return str(dest)
    except Exception as e:
        log(f"[{ts()}] file download failed: {e!r}", flush=True)
        return ""


def _opencode_bin(cfg) -> str:
    explicit = (cfg.get("OPENCODE_BIN") or "").strip()
    if explicit:
        return explicit
    local = pathlib.Path.home() / ".opencode" / "bin" / "opencode"
    return str(local) if local.exists() else "opencode"


def _opencode_api(cfg, method, path, body=None, timeout=60):
    """Call the OpenCode HTTP API via the CLI; returns parsed JSON."""
    cmd = [_opencode_bin(cfg), "api", method, path]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip().replace("\n", " ")[:180]
        raise RuntimeError(f"api {method} {path} rc={r.returncode}: {detail}")
    txt = (r.stdout or "").strip()
    return json.loads(txt) if txt else None


def start_opencode_listener(cfg):
    """Start the Telegram listener from an OpenCode MCP process if needed."""
    if (cfg.get("TG_AUTOSTART") or "1").strip().lower() in ("0", "false", "off", "no"):
        return
    try:
        BASE.mkdir(parents=True, exist_ok=True)
        if PID.exists():
            pid = int(PID.read_text().strip())
            os.kill(pid, 0)
            cmdline = pathlib.Path(f"/proc/{pid}/cmdline")
            if cmdline.exists() and b"tg_bridge.py\x00listen" in cmdline.read_bytes():
                return
    except (ValueError, OSError):
        pass
    try:
        lock_fd = os.open(BASE / ".listener.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            import fcntl
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            os.close(lock_fd)
            raise RuntimeError("automatic listener locking requires fcntl on this platform")
        except BlockingIOError:
            os.close(lock_fd)
            return
        subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve()), "listen"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True,
                         close_fds=True)
    except Exception as e:
        log(f"[{ts()}] listener auto-start failed: {e!r}", flush=True)


def _updated(s: dict) -> float:
    return float(((s.get("time") or {}).get("updated")) or 0)


def _session_items(cfg, query: str):
    data = _opencode_api(
        cfg, "get", f"/api/session?order=desc&limit=100&parentID=null{query}"
    )
    if isinstance(data, dict):
        return data.get("data") or []
    return data or []


def list_sessions(cfg):
    """Return recent, non-archived root sessions in the current home directory."""
    home = urllib.parse.quote(str(pathlib.Path.home()))
    try:
        items = _session_items(cfg, f"&directory={home}")
    except Exception as e:
        log(f"[{ts()}] session listing failed: {e!r}", flush=True)
        return []
    return [s for s in items if isinstance(s, dict) and not s.get("parentID")
            and not (s.get("time") or {}).get("archived")
            and (not s.get("directory") or pathlib.Path(str(s["directory"])).resolve()
                 == pathlib.Path.home().resolve())]


def _active_session_id():
    try:
        data = json.loads(ACTIVE_SESSION.read_text(encoding="utf-8"))
        return str(data.get("id") or "")
    except (OSError, ValueError, TypeError):
        return ""


def _set_active_session(session):
    """Persist the selected session atomically; no settings/env edits required."""
    ACTIVE_SESSION.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACTIVE_SESSION.with_suffix(".tmp")
    payload = json.dumps({"id": session.get("id"),
                          "title": session.get("title") or "Untitled",
                          "directory": session.get("directory") or ""},
                         ensure_ascii=False).encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(payload)
    os.replace(tmp, ACTIVE_SESSION)


def _keyboard(cfg):
    return {"keyboard": [[{"text": "Sessions"}, {"text": "Current session"}],
                         [{"text": "Models"}, {"text": "Help"}]],
            "resize_keyboard": True, "is_persistent": True,
            "input_field_placeholder": "Send a request to the selected session"}


def _send_keyboard(cfg):
    try:
        api(cfg["TG_BOT_TOKEN"], "sendMessage", {
            "chat_id": cfg["TG_CHAT_ID"],
            "text": "TeleCode is ready. Select a session, then send a message.",
            "reply_markup": json.dumps(_keyboard(cfg), ensure_ascii=False)}, timeout=15)
    except Exception as e:
        log(f"[{ts()}] keyboard setup failed: {e!r}", flush=True)


def session_title(session):
    title = str((session or {}).get("title") or "Untitled").replace("\n", " ").strip()
    return title[:36] or "Untitled"


def session_label(session):
    return f"{session_title(session)} [{str((session or {}).get('id') or '')}]"


def _session_buttons(sessions):
    """Name-first keyboard labels; codes only disambiguate duplicate names."""
    counts = {}
    for session in sessions:
        counts[session_title(session)] = counts.get(session_title(session), 0) + 1
    labels = {}
    for session in sessions:
        title = session_title(session)
        sid = str(session.get("id") or "")
        labels[sid] = title if counts[title] == 1 else f"{title} [{sid[-6:]}]"
    return labels


def _send_session_picker(cfg, page=0):
    global SESSION_PAGE
    sessions = list_sessions(cfg)
    if not sessions:
        send_text(cfg, "No recent OpenCode sessions were found in the home directory.")
        _send_keyboard(cfg)
        return
    SESSION_PAGE = min(max(0, page), (len(sessions) - 1) // SESSION_PAGE_SIZE)
    start = SESSION_PAGE * SESSION_PAGE_SIZE
    visible = sessions[start:start + SESSION_PAGE_SIZE]
    if not visible:
        SESSION_PAGE = 0
        _send_session_picker(cfg, 0)
        return
    labels = _session_buttons(sessions)
    rows = [[{"text": labels[str(s.get("id") or "")]}] for s in visible]
    nav = []
    if SESSION_PAGE > 0:
        nav.append({"text": "Previous"})
    if start + SESSION_PAGE_SIZE < len(sessions):
        nav.append({"text": "Next"})
    if nav:
        rows.append(nav)
    rows.append([{"text": "Cancel"}])
    active = _active_session_id()
    if not active:
        active = (cfg.get("OPENCODE_SESSION_ID") or "").strip()
    if not active:
        active = discover_session(cfg) or ""
    text = "*Choose a session*\nSelect the destination for your Telegram messages."
    text += "\n" + "\n".join(
        f"{start + index}\\. *{_mdv2_escape(session_title(s))}* — `{_mdv2_escape(s.get('id', ''))}`"
        + (" \\(active\\)" if s.get("id") == active else "")
        for index, s in enumerate(visible, start=1))
    api(cfg["TG_BOT_TOKEN"], "sendMessage", {
        "chat_id": cfg["TG_CHAT_ID"], "text": text,
        "parse_mode": "MarkdownV2",
        "reply_markup": json.dumps({"keyboard": rows, "resize_keyboard": True,
                                     "is_persistent": True}, ensure_ascii=False)}, timeout=15)


def _mdv2_escape(value):
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", lambda match: "\\" + match.group(1), str(value))


def _send_inline(cfg, text, rows, parse_mode="MarkdownV2"):
    api(cfg["TG_BOT_TOKEN"], "sendMessage", {
        "chat_id": cfg["TG_CHAT_ID"], "text": text, "parse_mode": parse_mode,
        "reply_markup": json.dumps({"inline_keyboard": rows}, ensure_ascii=False)}, timeout=15)


def _models_from_api(cfg):
    data = _opencode_api(cfg, "get", "/api/model", timeout=45)
    items = data.get("data") if isinstance(data, dict) else data
    out = []
    for model in items or []:
        if not isinstance(model, dict):
            continue
        mid = str(model.get("modelID") or model.get("id") or "").strip()
        provider = str(model.get("providerID") or "").strip()
        if not mid or not provider:
            continue
        out.append({"id": mid, "providerID": provider,
                    "name": str(model.get("name") or mid)})
    return out


def _write_models_cache(models):
    temp = MODELS_CACHE.with_name(f".models-cache.{os.getpid()}.tmp")
    MODELS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    temp.write_text(json.dumps({"saved": int(time.time()), "models": models},
                               ensure_ascii=False), encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, MODELS_CACHE)


def _read_models_cache():
    try:
        payload = json.loads(MODELS_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    return [m for m in models if isinstance(m, dict) and m.get("id") and m.get("providerID")]


def _group_models(models):
    groups = {}
    for model in models:
        groups.setdefault(str(model["providerID"]), []).append(model)
    return {p: sorted(items, key=lambda m: str(m.get("name", "")).lower())
            for p, items in groups.items()}


def _ordered_providers(groups):
    return sorted(groups, key=lambda p: (-len(groups[p]), p))


def _current_model(cfg, sid):
    if not sid:
        return ""
    try:
        data = _opencode_api(cfg, "get",
                             f"/api/session/{urllib.parse.quote(sid, safe='')}", timeout=20)
    except Exception:
        return ""
    info = data.get("data") if isinstance(data, dict) else data
    model = (info or {}).get("model") or {}
    return str(model.get("id") or "")


def _models_menu(cfg, provider_index=None, page=0):
    """Send the provider/model picker as inline buttons."""
    try:
        models = _models_from_api(cfg)
        if models:
            _write_models_cache(models)
    except Exception as e:
        log(f"[{ts()}] model listing failed: {e!r}", flush=True)
        models = _read_models_cache()
    if not models:
        send_text(cfg, "Unable to load models from OpenCode. Check that the service is running, then send /models again.")
        return
    groups = _group_models(models)
    providers = _ordered_providers(groups)
    sid, _ = resolve_session(cfg)
    current = _current_model(cfg, sid)
    if provider_index is None:
        header = "*Choose a model provider*"
        if current:
            header += f"\nCurrent model: `{_mdv2_escape(current)}`"
        rows = [[{"text": f"{provider} ({len(groups[provider])})",
                  "callback_data": f"mdl:p:{index}"}]
                for index, provider in enumerate(providers)]
        rows.append([{"text": "Close", "callback_data": "mdl:x"}])
        _send_inline(cfg, header, rows)
        return
    try:
        provider_index = int(provider_index)
    except (TypeError, ValueError):
        provider_index = 0
    if not 0 <= provider_index < len(providers):
        provider_index = 0
    provider = providers[provider_index]
    items = groups[provider]
    pages = max(1, (len(items) + MODELS_PAGE_SIZE - 1) // MODELS_PAGE_SIZE)
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 0
    page = min(max(0, page), pages - 1)
    start = page * MODELS_PAGE_SIZE
    rows = []
    for offset, model in enumerate(items[start:start + MODELS_PAGE_SIZE]):
        name = str(model.get("name") or model["id"])[:32]
        name = _mdv2_escape(name)
        if current and model["id"] == current:
            name = "Current: " + name
        rows.append([{"text": name,
                      "callback_data": f"mdl:s:{provider_index}:{start + offset}"}])
    nav = []
    if page > 0:
        nav.append({"text": "Previous", "callback_data": f"mdl:l:{provider_index}:{page - 1}"})
    if page + 1 < pages:
        nav.append({"text": "Next", "callback_data": f"mdl:l:{provider_index}:{page + 1}"})
    if nav:
        rows.append(nav)
    rows.append([{"text": "Providers", "callback_data": "mdl:r"},
                 {"text": "Close", "callback_data": "mdl:x"}])
    text = f"*{_mdv2_escape(provider)}* — Select a model ({page + 1}/{pages})"
    if current:
        text += f"\nCurrent model: `{_mdv2_escape(current)}`"
    _send_inline(cfg, text, rows)


def _switch_session_model(cfg, model):
    sid, how = resolve_session(cfg)
    if not sid:
        send_text(cfg, "No active session is available for model switching.")
        return
    model_name = _mdv2_escape(model.get("name") or model.get("id") or "model")
    provider = _mdv2_escape(model.get("providerID") or "")
    session_name = _mdv2_escape(session_title(_session_by_id(cfg, sid) or {"id": sid}))
    _opencode_api(
        cfg, "post", f"/api/session/{urllib.parse.quote(sid, safe='')}/model",
        {"model": {"id": model["id"], "providerID": model["providerID"]}}, timeout=30)
    log(f"[{ts()}] model switch sid={sid} ({how}) -> {model['providerID']}/{model['id']}", flush=True)
    send_text(cfg, f"*Model switched*\n{model_name} (`{provider}`)\nSession: {session_name}", parse_mode="MarkdownV2")


def handle_callback(cfg, cb):
    """Handle inline-keyboard callbacks (owner only; enforced by caller)."""
    data = str(cb.get("data") or "")
    callback_id = str(cb.get("id") or "")
    if callback_id:
        try:
            api(cfg["TG_BOT_TOKEN"], "answerCallbackQuery",
                {"callback_query_id": callback_id}, timeout=10)
        except Exception as e:
            log(f"[{ts()}] answerCallbackQuery failed: {e!r}", flush=True)
    if data == "mdl:x":
        return True
    if data == "mdl:r":
        _models_menu(cfg)
        return True
    parts = data.split(":")
    try:
        if len(parts) == 3 and parts[1] == "p":
            _models_menu(cfg, int(parts[2]))
            return True
        if len(parts) == 4 and parts[1] == "l":
            _models_menu(cfg, int(parts[2]), int(parts[3]))
            return True
        if len(parts) == 4 and parts[1] == "s":
            groups = _group_models(_read_models_cache())
            providers = _ordered_providers(groups)
            provider_index, model_index = int(parts[2]), int(parts[3])
            if not (0 <= provider_index < len(providers)):
                send_text(cfg, "This model list expired. Send /models to open a fresh list.")
                return True
            items = groups[providers[provider_index]]
            if not (0 <= model_index < len(items)):
                send_text(cfg, "This model list expired. Send /models to open a fresh list.")
                return True
            try:
                _switch_session_model(cfg, items[model_index])
            except Exception as e:
                log(f"[{ts()}] model switch failed: {e!r}", flush=True)
                send_text(cfg, f"Model switch failed: {_mdv2_escape(str(e)[:140])}", parse_mode="MarkdownV2")
            return True
    except (TypeError, ValueError):
        return False
    return False


def handle_control_message(cfg, msg, text):
    """Handle Telegram keyboard commands before normal agent injection."""
    cmd = (text or "").strip()
    if cmd.startswith("/") and "@" in cmd:
        cmd = cmd.split("@", 1)[0]
    if cmd in ("/start", "/help", "Help"):
        _send_keyboard(cfg)
        send_text(cfg, "*Commands*\n/session selects a session\n/current shows the active target\n/models switches its model\n/files lists received files\n\nSend any text to the active session. Agent replies arrive through the `tg_send` and `tg_sendfile` MCP tools.", parse_mode="MarkdownV2")
        return True
    if cmd in ("/session", "Sessions"):
        _send_session_picker(cfg)
        return True
    if cmd in ("/models", "/model", "Models"):
        _models_menu(cfg)
        return True
    if cmd in ("/files", "Files"):
        sid, _ = resolve_session(cfg)
        directory = FILES / (sid if sid else "unassigned")
        entries = sorted((p for p in directory.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True) if directory.exists() else []
        if not entries:
            send_text(cfg, "No files have been received for the active session.")
        else:
            send_text(cfg, "Files for this session:\n" + "\n".join(str(p) for p in entries[:20]))
        return True
    if cmd in ("/current", "Current session"):
        sid, _ = resolve_session(cfg)
        session = next((s for s in list_sessions(cfg) if s.get("id") == sid), None)
        if session:
            send_text(cfg, f"*Active session:* {_mdv2_escape(session_title(session))}\n*Session ID:* `{_mdv2_escape(sid)}`", parse_mode="MarkdownV2")
        else:
            send_text(cfg, f"Active session: `{_mdv2_escape(sid or 'not set')}`", parse_mode="MarkdownV2")
        return True
    if cmd == "Cancel":
        _send_keyboard(cfg)
        return True
    if cmd == "Next":
        _send_session_picker(cfg, SESSION_PAGE + 1)
        return True
    if cmd == "Previous":
        _send_session_picker(cfg, max(0, SESSION_PAGE - 1))
        return True
    sessions = list_sessions(cfg)
    labels = _session_buttons(sessions)
    matches = [s for s in sessions if labels.get(str(s.get("id") or "")) == cmd]
    if not matches:
        shared = [s for s in sessions if session_title(s) == cmd]
        if len(shared) > 1:
            send_text(cfg, "That name matches multiple sessions. Open /session and choose the entry with the matching short ID.")
            return True
    for session in matches:
        if labels.get(str(session.get("id") or "")) == cmd:
            sid = str(session.get("id") or "")
            if not re.fullmatch(r"ses[0-9A-Za-z_-]{6,80}", sid):
                send_text(cfg, "Invalid session ID; the target was not changed.")
                return True
            _set_active_session(session)
            SESSION_PAGE = 0
            try:
                send_text(cfg, f"*Target session:* {_mdv2_escape(session_title(session))}\n*Session ID:* `{_mdv2_escape(sid)}`", parse_mode="MarkdownV2")
            except Exception as e:
                log(f"[{ts()}] session-switch notification failed: {e!r}", flush=True)
            _send_keyboard(cfg)
            return True
    if re.search(r"\[ses[0-9A-Za-z_-]{6,80}\]$", cmd):
        send_text(cfg, "The selected session is no longer available. Open /session and choose another target.")
        return True
    return False


def discover_session(cfg):
    """Newest non-archived root session (prefers this home directory)."""
    home = urllib.parse.quote(str(pathlib.Path.home()))
    for query in (f"&directory={home}",):
        try:
            items = _session_items(cfg, query)
        except Exception as e:
            log(f"[{ts()}] discovery failed: {e!r}", flush=True)
            continue
        best = None
        for s in items:
            if not isinstance(s, dict) or s.get("parentID"):
                continue
            if (s.get("time") or {}).get("archived"):
                continue
            directory = s.get("directory")
            if directory and pathlib.Path(str(directory)).resolve() != pathlib.Path.home().resolve():
                continue
            if best is None or _updated(s) > _updated(best):
                best = s
        if best:
            return best.get("id") or None
    return None


def _session_by_id(cfg, sid):
    if not re.fullmatch(r"ses[0-9A-Za-z_-]{6,80}", str(sid or "")):
        return None
    return next((s for s in list_sessions(cfg) if str(s.get("id")) == sid), None)


def resolve_session(cfg):
    """Resolve the injection target session (auto-discovery by default)."""
    selected = _active_session_id()
    if selected and re.fullmatch(r"ses[0-9A-Za-z_-]{6,80}", selected):
        # Do not route stale or cross-directory selections into another project.
        if _session_by_id(cfg, selected):
            return selected, "telegram-selected"
        try:
            if _active_session_id() == selected:
                ACTIVE_SESSION.unlink(missing_ok=True)
        except OSError:
            pass
    mode = (cfg.get("OPENCODE_SESSION_MODE") or "auto").strip().lower()
    pin = (cfg.get("OPENCODE_SESSION_ID") or "").strip()
    if mode in ("pin", "pinned") and pin and re.fullmatch(r"ses[0-9A-Za-z_-]{6,80}", pin):
        return pin, "pinned"
    sid = discover_session(cfg)
    if sid and re.fullmatch(r"ses[0-9A-Za-z_-]{6,80}", sid):
        return sid, "discovered"
    return "", "none"


def _try_prompt(cfg, sid, body_text, delivery):
    """One admit attempt into a session. Returns True on success."""
    if not re.fullmatch(r"ses[0-9A-Za-z_-]{6,80}", str(sid)):
        log(f"[{ts()}] prompt rejected invalid session id", flush=True)
        return False
    body = json.dumps({"text": body_text, "delivery": delivery})
    cmd = [_opencode_bin(cfg), "api", "post", f"/api/session/{urllib.parse.quote(sid, safe='')}/prompt", "-d", body]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except Exception as e:
        log(f"[{ts()}] prompt sid={sid} {delivery}: error {e!r}", flush=True)
        return False
    tail = ((r.stdout or "").strip() + " " + (r.stderr or "").strip()).strip().replace("\n", " ")[:150]
    log(f"[{ts()}] prompt sid={sid} {delivery}: rc={r.returncode} {tail}", flush=True)
    return r.returncode == 0


def inject_record(cfg: dict, rec: dict) -> bool:
    """Admit one owner message into the live OpenCode session. Returns True on success."""
    text = (rec.get("text") or "").strip()
    if not text and not rec.get("file"):
        log(f"[{ts()}] inject skipped: empty update {rec.get('update_id')}", flush=True)
        return True  # nothing deliverable; treat as done
    body_text = text
    if rec.get("file"):
        body_text = (body_text + "\n" if body_text else "") + f"[attached file: {rec['file']}]"

    delivery = (cfg.get("TG_DELIVERY") or "steer").strip().lower()
    if delivery not in ("steer", "queue"):
        delivery = "steer"
    sid, how = resolve_session(cfg)
    if not sid:
        log(f"[{ts()}] inject: no session found (update={rec.get('update_id')})", flush=True)
        return False
    queued_for = str(rec.get("session_id") or "")
    if queued_for and queued_for != sid:
        # A session switch happened while this update waited in the queue.
        # Preserve the original target rather than silently rerouting it.
        if not _session_by_id(cfg, queued_for):
            send_text(cfg, "Could not deliver this message to its original session because that session is no longer available. Select a session and resend.")
            return True
        sid = queued_for
        how = "captured-at-receive"
    log(f"[{ts()}] inject target sid={sid} ({how}), delivery={delivery}", flush=True)
    if _try_prompt(cfg, sid, body_text, delivery):
        STATE.write_text(sid)
        return True
    if delivery != "queue" and _try_prompt(cfg, sid, body_text, "queue"):
        STATE.write_text(sid)
        return True
    return False


def _inject_worker(cfg: dict) -> None:
    mode = (cfg.get("OPENCODE_INJECT") or "1").strip().lower()
    if mode in ("0", "false", "off", "no"):
        log(f"[{ts()}] inject worker inactive (mode={mode!r})", flush=True)
        return
    log(f"[{ts()}] inject worker up: delivery={cfg.get('TG_DELIVERY') or 'steer'}", flush=True)
    while True:
        rec = INJECT_Q.get()
        try:
            try:
                ok = inject_record(cfg, rec)
            except Exception:
                ok = False
                log(f"[{ts()}] inject exception update={rec.get('update_id')}:", flush=True)
                log(traceback.format_exc(), flush=True)
            tries = int(rec.get("_tries", 0))
            if not ok and tries < 12:
                rec["_tries"] = tries + 1
                log(f"[{ts()}] retry {tries + 1}/12 update={rec.get('update_id')} in 25s", flush=True)
                timer = threading.Timer(25, INJECT_Q.put, args=(rec,))
                timer.daemon = True
                timer.start()
            elif not ok:
                log(f"[{ts()}] gave up update={rec.get('update_id')} (kept in inbox.jsonl)", flush=True)
        finally:
            INJECT_Q.task_done()


def cmd_listen():
    cfg = load_env()
    token = cfg["TG_BOT_TOKEN"]
    owner = str(cfg["TG_CHAT_ID"])
    BASE.mkdir(parents=True, exist_ok=True)
    lock_path = BASE / ".listener.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        import fcntl
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (ImportError, BlockingIOError):
        log(f"[{ts()}] listener already running; exiting", flush=True)
        # Child takes the same lock in cmd_listen; release parent descriptor only
        # after the process has been spawned, avoiding simultaneous start races.
        os.close(lock_fd)
        return 0
    offset = int(OFFSET.read_text().strip()) if OFFSET.exists() else 0
    PID.write_text(str(os.getpid()))
    log(f"[{ts()}] listener up (pid {os.getpid()}), owner={owner}, offset={offset}", flush=True)
    _send_keyboard(cfg)
    threading.Thread(target=_inject_worker, args=(cfg,), daemon=True).start()
    while True:
        try:
            res = api(
                token,
                "getUpdates",
                {"offset": offset, "timeout": 50,
                 "allowed_updates": json.dumps(["message", "callback_query"])},
                timeout=65,
            )
            for u in res.get("result", []):
                offset = u["update_id"] + 1
                cb = u.get("callback_query")
                if cb:
                    cb_chat = str(((cb.get("message") or {}).get("chat") or {}).get("id", ""))
                    cb_sender = str((cb.get("from") or {}).get("id", ""))
                    if cb_chat != owner or cb_sender != owner:
                        log(f"[{ts()}] ignored callback from unauthorized chat {cb_chat}", flush=True)
                        OFFSET.write_text(str(offset))
                        continue
                    try:
                        handle_callback(cfg, cb)
                    except Exception:
                        log(f"[{ts()}] callback error:", flush=True)
                        log(traceback.format_exc(), flush=True)
                    OFFSET.write_text(str(offset))
                    continue
                msg = u.get("message") or {}
                chat_id = str((msg.get("chat") or {}).get("id", ""))
                text = msg.get("text") or msg.get("caption") or ""
                if chat_id != owner:
                    log(f"[{ts()}] ignored update {u['update_id']} from unauthorized chat {chat_id}", flush=True)
                    OFFSET.write_text(str(offset))
                    continue
                sender_id = str((msg.get("from") or {}).get("id", ""))
                if sender_id and sender_id != owner:
                    log(f"[{ts()}] ignored update {u['update_id']} from sender {sender_id}", flush=True)
                    OFFSET.write_text(str(offset))
                    continue
                if handle_control_message(cfg, msg, text):
                    OFFSET.write_text(str(offset))
                    continue
                file_id, file_name = None, ""
                doc = msg.get("document")
                photo = msg.get("photo")
                if doc:
                    file_id = doc.get("file_id")
                    file_name = doc.get("file_name") or f"document_{msg.get('message_id')}"
                elif photo:
                    file_id = photo[-1].get("file_id")
                    file_name = f"photo_{msg.get('message_id')}.jpg"
                active_sid, _ = resolve_session(cfg)
                session_files = FILES / (active_sid if active_sid else "unassigned")
                session_files.mkdir(parents=True, exist_ok=True)
                if file_id:
                    saved = _download_file(token, file_id, file_name, destination=session_files)
                else:
                    saved = ""
                rec = {
                    "ts": int(time.time()), "iso": ts(), "update_id": u["update_id"],
                    "chat_id": chat_id, "text": text, "file": saved, "file_name": file_name,
                    "session_id": active_sid,
                }
                with INBOX.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                OFFSET.write_text(str(offset))
                log(f"[{ts()}] stored update {u['update_id']}: {text[:80]} | file={saved}", flush=True)
                INJECT_Q.put(rec)
        except KeyboardInterrupt:
            break
        except Exception as e:  # keep the daemon alive across network hiccups
            log(f"[{ts()}] poll error: {e!r}", flush=True)
            time.sleep(5)


def _cursor():
    return int(CURSOR.read_text().strip()) if CURSOR.exists() else 0


def _unread():
    cur = _cursor()
    out = []
    if INBOX.exists():
        for line in INBOX.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if int(rec.get("update_id", 0)) > cur:
                out.append(rec)
    return out


def _advance(recs):
    if recs:
        CURSOR.write_text(str(max(int(r["update_id"]) for r in recs)))


def cmd_read():
    recs = _unread()
    for r in recs:
        line = f"[{r['iso']}] {r['text']}"
        if r.get("file"):
            line += f"\n    FILE: {r['file']}"
        print(line)
    _advance(recs)
    return 0


def cmd_wait():
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    deadline = time.time() + seconds
    while time.time() < deadline:
        recs = _unread()
        if recs:
            for r in recs:
                line = f"[{r['iso']}] {r['text']}"
                if r.get("file"):
                    line += f"\n    FILE: {r['file']}"
                print(line)
            _advance(recs)
            return 0
        time.sleep(2)
    print(f"TIMEOUT: no message within {seconds}s")
    return 3


def send_text(cfg, text, parse_mode=None):
    """Send a message to the owner chat; returns message_id."""
    chunks = []
    remaining = str(text)
    while len(remaining) > 4000:
        split_at = remaining.rfind("\n", 0, 4000)
        if split_at < 1000:
            split_at = 4000
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    chunks.append(remaining)
    mid = None
    for chunk in chunks:
        res = api(
            cfg["TG_BOT_TOKEN"],
            "sendMessage",
            {"chat_id": cfg["TG_CHAT_ID"], "text": chunk,
             "disable_web_page_preview": "true",
             **({"parse_mode": parse_mode} if parse_mode else {})},
            timeout=30,
        )
        mid = (res.get("result") or {}).get("message_id")
    return mid


def send_file(cfg, path, caption=""):
    """Send a document to the owner chat; returns message_id."""
    if not path.is_file() or path.is_symlink():
        raise ValueError("send_file requires a regular non-symlink file")
    if path.stat().st_size > 49 * 1024 * 1024:
        raise ValueError("file too large for Telegram (limit ~50MB)")
    caption = str(caption).replace("\r", " ").replace("\n", " ")[:1024]
    boundary = "----tgbridge" + secrets.token_hex(16)
    body = b""
    fields = [("chat_id", str(cfg["TG_CHAT_ID"]))]
    if caption:
        fields.append(("caption", caption))
    for name, value in fields:
        value = str(value).replace("\r", " ").replace("\n", " ")
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        ).encode("utf-8")
    filename = path.name.replace("\r", "_").replace("\n", "_").replace('"', "_")
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="document"; '
        f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
    ).encode("utf-8")
    body += path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{cfg['TG_BOT_TOKEN']}/sendDocument",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=180) as r:
        res = json.loads(r.read().decode("utf-8"))
    return (res.get("result") or {}).get("message_id")


def cmd_send():
    cfg = load_env()
    text = " ".join(sys.argv[2:]).strip() if len(sys.argv) > 2 else sys.stdin.read().strip()
    if not text:
        print("usage: tg_bridge.py send <text>   (or pipe text via stdin)", file=sys.stderr)
        return 2
    mid = send_text(cfg, text)
    print(f"sent ok (message_id={mid})")
    return 0


def cmd_sendfile():
    cfg = load_env()
    if len(sys.argv) < 3:
        print("usage: tg_bridge.py sendfile <path> [caption]", file=sys.stderr)
        return 2
    path = pathlib.Path(os.path.expanduser(sys.argv[2]))
    caption = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
    if not path.is_file() or path.is_symlink():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    mid = send_file(cfg, path, caption)
    print(f"sent file ok (message_id={mid})")
    return 0


def cmd_status():
    cfg = load_env()
    me = api(cfg["TG_BOT_TOKEN"], "getMe", timeout=15)
    bot = me.get("result") or {}
    alive = "down"
    if PID.exists():
        pid = PID.read_text().strip()
        try:
            os.kill(int(pid), 0)
            alive = f"up (pid {pid})"
        except Exception:
            alive = f"stale pid {pid}"
    print(f"bot: @{bot.get('username')} (id {bot.get('id')})")
    print(f"owner chat: {cfg.get('TG_CHAT_ID')}")
    print(f"listener: {alive}")
    sid, how = resolve_session(cfg)
    print(f"inject target: {sid or '(none)'} [{how}]")
    print(f"delivery: {cfg.get('TG_DELIVERY') or 'steer'} (session mode: {cfg.get('OPENCODE_SESSION_MODE') or 'auto'})")
    if STATE.exists():
        print(f"last delivered session: {STATE.read_text().strip()}")
    print(f"unread: {len(_unread())}")
    return 0


def cmd_install():
    """Install the current checkout as a user-level systemd service."""
    source = pathlib.Path(__file__).resolve().parent
    script = source / "install.sh"
    if not script.is_file():
        print("installer not found; use the release install.sh", file=sys.stderr)
        return 2
    return subprocess.call(["bash", str(script), "--enable"])


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        args = ["bash", str(pathlib.Path(__file__).resolve().parent / "install.sh")]
        if len(sys.argv) > 2:
            args.extend(sys.argv[2:])
        return subprocess.call(args)
    cmds = {
        "listen": cmd_listen, "read": cmd_read, "wait": cmd_wait,
        "send": cmd_send, "sendfile": cmd_sendfile, "status": cmd_status,
        "install": cmd_install,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("usage: tg_bridge.py {listen|read|wait SECONDS|send TEXT|sendfile PATH [CAPTION]|status|install}", file=sys.stderr)
        return 2
    return cmds[sys.argv[1]]() or 0


if __name__ == "__main__":
    sys.exit(main())
