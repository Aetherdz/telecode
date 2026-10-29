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
import atexit
import json
import os
import pathlib
import queue
import re
import secrets
import signal
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
SESSION_PAGE_SIZE = 20
MODELS_PAGE_SIZE = 20
MODEL_PAGE_STATE = {"provider_index": None, "page": 0}
MODEL_BACK = "Back to providers"
MODEL_BACK_MAIN = "Back"
MODEL_PREVIOUS = "Previous"
MODEL_NEXT = "Next"
MODEL_CLOSE = "Cancel"
NEW_SESSION = "New session"
CREATE_SESSION = "Create session"
SESSION_NAME_MAX_LENGTH = 80
MODEL_SELECTION = {"provider": None, "page": 0, "labels": {}}
SESSION_BUTTONS = {}
ACTIVE_PICKER = None
SESSION_PAGE = 0
SESSION_SNAPSHOT = []
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


def create_session(cfg, title):
    """Create a root OpenCode session in the user's home directory."""
    title = " ".join(str(title or "").split())
    if not title:
        raise ValueError("Session name is required.")
    if len(title) > SESSION_NAME_MAX_LENGTH:
        raise ValueError(f"Session name must be {SESSION_NAME_MAX_LENGTH} characters or fewer.")
    result = _opencode_api(
        cfg, "post", "/api/session",
        {"title": title, "directory": str(pathlib.Path.home().resolve())}, timeout=30)
    session = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), dict) else result
    if not isinstance(session, dict):
        raise RuntimeError("OpenCode did not return the created session.")
    sid = str(session.get("id") or "")
    if not re.fullmatch(r"ses[0-9A-Za-z_-]{6,80}", sid):
        raise RuntimeError("OpenCode returned an invalid session ID.")
    directory = str(session.get("directory") or pathlib.Path.home().resolve())
    home = pathlib.Path.home().resolve()
    try:
        if pathlib.Path(directory).resolve() != home:
            raise RuntimeError("OpenCode created the session outside the configured home directory.")
    except (OSError, RuntimeError) as e:
        raise RuntimeError("OpenCode created the session outside the configured home directory.") from e
    return {"id": sid, "title": str(session.get("title") or title), "directory": str(home)}


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
        cfg, "get", f"/api/session?order=desc&limit=1000&parentID=null{query}", timeout=30
    )
    if isinstance(data, dict):
        return data.get("data") or []
    return data or []


def list_sessions(cfg):
    """Return non-archived root sessions, falling back to an unfiltered API query."""
    home = urllib.parse.quote(str(pathlib.Path.home()), safe="")
    try:
        items = _session_items(cfg, f"&directory={home}")
        if not items:
            items = _session_items(cfg, "")
    except Exception as e:
        log(f"[{ts()}] session listing failed: {e!r}", flush=True)
        try:
            items = _session_items(cfg, "")
        except Exception as fallback_error:
            log(f"[{ts()}] unfiltered session listing failed: {fallback_error!r}", flush=True)
            return []
    home_path = pathlib.Path.home().resolve()
    sessions = []
    for session in items:
        if not isinstance(session, dict) or session.get("parentID"):
            continue
        if (session.get("time") or {}).get("archived"):
            continue
        directory = str(session.get("directory") or "")
        if directory:
            try:
                if pathlib.Path(directory).resolve() != home_path:
                    continue
            except (OSError, RuntimeError):
                continue
        sessions.append(session)
    return sessions


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
                         [{"text": "New session"}, {"text": "Models"}],
                         [{"text": "Help"}],
                         [{"text": "/menu"}, {"text": "/session"},
                          {"text": "/models"}]],
            "resize_keyboard": True, "one_time_keyboard": True}


def _configure_commands(cfg):
    try:
        api(cfg["TG_BOT_TOKEN"], "setMyCommands", {"commands": json.dumps([
            {"command": "menu", "description": "Show the TeleCode keyboard"},
            {"command": "session", "description": "Choose the active session"},
            {"command": "models", "description": "Choose a model"},
            {"command": "model", "description": "Choose a model"},
            {"command": "current", "description": "Show the active session"},
            {"command": "files", "description": "List received files"},
            {"command": "start", "description": "Show TeleCode controls"},
            {"command": "help", "description": "Show available commands"},
        ])}, timeout=15)
    except Exception as e:
        log(f"[{ts()}] bot command menu setup failed: {e!r}", flush=True)


def _send_keyboard(cfg, text="TeleCode menu", *, configure=False, parse_mode=None):
    try:
        if configure:
            _configure_commands(cfg)
        params = {
            "chat_id": cfg["TG_CHAT_ID"],
            "text": text,
            "reply_markup": json.dumps(_keyboard(cfg), ensure_ascii=False),
        }
        if parse_mode:
            params["parse_mode"] = parse_mode
        api(cfg["TG_BOT_TOKEN"], "sendMessage", params, timeout=15)
    except Exception as e:
        log(f"[{ts()}] keyboard setup failed: {e!r}", flush=True)


SESSION_MESSAGE_ID = None
LAST_SESSION_LABELS = set()


def _delete_message(cfg, message_id):
    """Best-effort removal of a previous picker message."""
    if not message_id:
        return
    try:
        api(cfg["TG_BOT_TOKEN"], "deleteMessage",
            {"chat_id": cfg["TG_CHAT_ID"], "message_id": str(message_id)}, timeout=10)
    except Exception as e:
        log(f"[{ts()}] could not delete picker message: {e!r}", flush=True)


def _clear_session_picker(cfg):
    global SESSION_MESSAGE_ID
    _delete_message(cfg, SESSION_MESSAGE_ID)
    SESSION_MESSAGE_ID = None


def _send_picker_notice(cfg, text):
    """Compatibility hook; avoid creating another chat message for transitions."""
    return None


def _invalidate_model_message_ref():
    try:
        path = MODELS_CACHE.with_name("models-message.json")
        path.unlink(missing_ok=True)
    except OSError as e:
        log(f"[{ts()}] could not invalidate model-picker reference: {e!r}", flush=True)


def _hide_picker_keyboard(cfg):
    """Compatibility shim retained for callers; do not re-send a keyboard."""
    return None


def session_title(session):
    title = str((session or {}).get("title") or "Untitled").replace("\n", " ").strip()
    return title[:60] or "Untitled"


def session_label(session):
    return f"{session_title(session)} [{str((session or {}).get('id') or '')}]"


def _session_buttons(sessions):
    """Use clean titles; add a numeric suffix only when titles collide."""
    reserved = {
        "Cancel", "Next", "Previous", MODEL_CLOSE, MODEL_BACK, MODEL_BACK_MAIN,
        MODEL_PREVIOUS, MODEL_NEXT, "Sessions", "Models", "Help",
        "Current session", NEW_SESSION, CREATE_SESSION,
        "Menu", "Show menu", "Files", "/menu", "/session",
        "/newsession", "/models", "/model", "/current",
        "/help", "/files",
    }
    counts = {}
    for session in sessions:
        title = session_title(session)
        counts[title] = counts.get(title, 0) + 1
    labels = {}
    used = set()
    seen = {}
    for session in sessions:
        title = session_title(session)
        sid = str(session.get("id") or "")
        if counts[title] > 1:
            seen[title] = seen.get(title, 0) + 1
            label = f"{title} ({seen[title]})"
        else:
            label = title
        if label in used or label in reserved:
            base = label
            number = 2
            while f"{base} ({number})" in used or f"{base} ({number})" in reserved:
                number += 1
            label = f"{base} ({number})"
        used.add(label)
        labels[sid] = label
    return labels


def _send_session_picker(cfg, page=0, sessions=None):
    global SESSION_PAGE, SESSION_SNAPSHOT, ACTIVE_PICKER
    sessions = list_sessions(cfg) if sessions is None else sessions
    if not sessions:
        global SESSION_SNAPSHOT, ACTIVE_PICKER
        SESSION_SNAPSHOT = []
        SESSION_BUTTONS.clear()
        MODEL_SELECTION.update(provider=None, page=0, labels={})
        ACTIVE_PICKER = "sessions"
        LAST_SESSION_LABELS.clear()
        _clear_session_picker(cfg)
        result = _send_reply_picker(cfg, "No sessions found",
                                    [[{"text": NEW_SESSION}], [{"text": "Cancel"}]], notify=False)
        SESSION_MESSAGE_ID = ((result or {}).get("result") or {}).get("message_id")
        return
    SESSION_SNAPSHOT = list(sessions)
    MODEL_SELECTION.update(provider=None, page=0, labels={})
    SESSION_PAGE = min(max(0, page), (len(sessions) - 1) // SESSION_PAGE_SIZE)
    start = SESSION_PAGE * SESSION_PAGE_SIZE
    visible = sessions
    labels = _session_buttons(sessions)
    rows = [[{"text": labels[str(s.get("id") or "")]}]
            for s in visible[start:start + SESSION_PAGE_SIZE]]
    rows.append([{"text": NEW_SESSION}])
    SESSION_BUTTONS.clear()
    SESSION_BUTTONS.update({labels[str(s.get("id") or "")]: str(s.get("id") or "")
                            for s in visible[start:start + SESSION_PAGE_SIZE]})
    LAST_SESSION_LABELS.clear()
    LAST_SESSION_LABELS.update(labels[str(s.get("id") or "")]
                               for s in visible[start:start + SESSION_PAGE_SIZE])
    ACTIVE_PICKER = "sessions"
    nav = []
    if SESSION_PAGE > 0:
        nav.append({"text": "Previous"})
    if start + SESSION_PAGE_SIZE < len(sessions):
        nav.append({"text": "Next"})
    if nav:
        rows.append(nav)
    rows.append([{"text": "Cancel"}])
    page_count = (len(sessions) - 1) // SESSION_PAGE_SIZE + 1
    text = "Sessions"
    if page_count > 1:
        text += f" {SESSION_PAGE + 1}/{page_count}"
    _clear_session_picker(cfg)
    result = _send_reply_picker(cfg, text, rows, notify=False)
    SESSION_MESSAGE_ID = ((result or {}).get("result") or {}).get("message_id")


def _begin_new_session(cfg):
    global ACTIVE_PICKER, SESSION_SNAPSHOT
    if ACTIVE_PICKER in ("models", "providers"):
        _invalidate_model_message_ref()
    ACTIVE_PICKER = "new-session-name"
    SESSION_SNAPSHOT = []
    SESSION_BUTTONS.clear()
    MODEL_SELECTION.update(provider=None, page=0, labels={})
    MODEL_PAGE_STATE.update(provider_index=None, page=0)
    _send_reply_picker(
        cfg,
        f"<b>New OpenCode session</b>\nSend the session name as your next message (up to {SESSION_NAME_MAX_LENGTH} characters). Send Cancel to stop.",
        [[{"text": "Cancel"}], [{"text": "/menu"}, {"text": "/session"},
         {"text": "/models"}, {"text": "/model"}, {"text": "/help"},
         {"text": "/current"}, {"text": "/files"}]],
        notify=False,
    )


def _restore_primary_controls():
    """Discard temporary picker state before routing to another control."""
    global ACTIVE_PICKER
    ACTIVE_PICKER = None
    SESSION_BUTTONS.clear()
    LAST_SESSION_LABELS.clear()
    SESSION_SNAPSHOT.clear()
    MODEL_SELECTION.update(provider=None, page=0, labels={})
    MODEL_SELECTION.pop("models", None)
    MODEL_PAGE_STATE.update(provider_index=None, page=0)


def _send_reply_picker(cfg, text, rows, notify=True):
    params = {
        "chat_id": cfg["TG_CHAT_ID"], "text": text, "parse_mode": "HTML",
        "reply_markup": json.dumps({
            "keyboard": rows,
            "resize_keyboard": True,
            "one_time_keyboard": True,
        }, ensure_ascii=False),
    }
    try:
        result = api(cfg["TG_BOT_TOKEN"], "sendMessage", params, timeout=15)
    except Exception as e:
        log(f"[{ts()}] formatted session picker failed; retrying as plain text: {e!r}", flush=True)
        params["text"] = _plain_fallback(text)
        params.pop("parse_mode", None)
        result = api(cfg["TG_BOT_TOKEN"], "sendMessage", params, timeout=15)
    if notify and result and result.get("result", {}).get("message_id"):
        _set_models_message_ref({"chat_id": cfg["TG_CHAT_ID"],
                                 "message_id": result["result"]["message_id"]})
    return result


def _html_escape(value):
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _plain_fallback(value):
    value = re.sub(r"</?(?:b|strong|i|em|u|s|strike|del|code|pre|a|blockquote)(?:\s+[^>]*)?>", "", str(value), flags=re.I)
    return (value.replace("&amp;", "&").replace("&lt;", "<")
            .replace("&gt;", ">"))


def _send_inline(cfg, text, rows):
    params = {
        "chat_id": cfg["TG_CHAT_ID"], "text": text, "parse_mode": "HTML",
        "reply_markup": json.dumps({"inline_keyboard": rows}, ensure_ascii=False),
    }
    try:
        return api(cfg["TG_BOT_TOKEN"], "sendMessage", params, timeout=15)
    except Exception as e:
        log(f"[{ts()}] formatted inline message failed; retrying as plain text: {e!r}", flush=True)
        params["text"] = _plain_fallback(text)
        params.pop("parse_mode", None)
        return api(cfg["TG_BOT_TOKEN"], "sendMessage", params, timeout=15)


def _edit_inline(cfg, message_ref, text, rows):
    """Edit the existing model-picker message instead of sending a new one."""
    message_ref = str(message_ref or "")
    try:
        message = json.loads(message_ref)
    except (TypeError, ValueError):
        message = {}
    chat_id = str(message.get("chat_id") or "")
    message_id = str(message.get("message_id") or "")
    if not chat_id or not message_id:
        return False
    params = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": json.dumps({"inline_keyboard": rows}, ensure_ascii=False),
    }
    try:
        result = api(cfg["TG_BOT_TOKEN"], "editMessageText", params, timeout=15)
    except Exception as e:
        log(f"[{ts()}] formatted model-menu edit failed; retrying as plain text: {e!r}", flush=True)
        params["text"] = _plain_fallback(text)
        params.pop("parse_mode", None)
        try:
            result = api(cfg["TG_BOT_TOKEN"], "editMessageText", params, timeout=15)
        except Exception as fallback_error:
            log(f"[{ts()}] model-menu edit fallback failed: {fallback_error!r}", flush=True)
            return False
    return bool(result and result.get("ok", True))


def _callback_message_ref(cb):
    message = cb.get("message") or {}
    chat_id = str(((message.get("chat") or {}).get("id")) or "")
    message_id = str(message.get("message_id") or "")
    if not chat_id or not message_id:
        return ""
    return json.dumps({"chat_id": chat_id, "message_id": message_id})


def _load_models_message_ref():
    try:
        value = json.loads(MODELS_CACHE.with_name("models-message.json").read_text(encoding="utf-8"))
        expires = int(value.get("expires", 0))
        if not value.get("chat_id") or not value.get("message_id") or expires < int(time.time()):
            return ""
        return json.dumps(value)
    except (OSError, ValueError, AttributeError):
        pass
    return ""


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


def _models_menu(cfg, provider_index=None, page=0, models_snapshot=None):
    """Show model-provider and model pages in Telegram's bottom reply keyboard."""
    global ACTIVE_PICKER
    if models_snapshot is not None:
        models = models_snapshot
    else:
        try:
            models = _models_from_api(cfg)
            if models:
                _write_models_cache(models)
        except Exception as e:
            log(f"[{ts()}] model listing failed: {e!r}", flush=True)
            models = _read_models_cache()
    if not models:
        ACTIVE_PICKER = None
        MODEL_SELECTION.update(provider=None, page=0, labels={})
        send_text(cfg, "Unable to load models from OpenCode. Check that the service is running, then send /models again.")
        return
    groups = _group_models(models)
    providers = _ordered_providers(groups)
    try:
        provider_index = None if provider_index is None else int(provider_index)
        page = int(page)
    except (TypeError, ValueError):
        provider_index, page = None, 0
    if provider_index is not None and not 0 <= provider_index < len(providers):
        provider_index = 0
    current = ""
    if provider_index is not None:
        sid, _ = resolve_session(cfg)
        current = _current_model(cfg, sid)
    if provider_index is None:
        ACTIVE_PICKER = "providers"
        MODEL_PAGE_STATE.update(provider_index=None, page=0)
        header = "<b>Choose a model provider</b>"
        if current:
            header += f"\nCurrent model: <code>{_html_escape(current)}</code>"
        rows = []
        provider_labels = {}
        reserved = {MODEL_CLOSE, MODEL_BACK, MODEL_BACK_MAIN, MODEL_PREVIOUS, MODEL_NEXT,
                    "Next", "Previous", "Sessions", "Models", "Help",
                    "Current session", "Cancel", "Menu", "Show menu", "Files",
                    "/menu", "/session", "/models", "/model", "/help"}
        for index, provider in enumerate(providers):
            base = f"{provider} ({len(groups[provider])})"
            label = base
            suffix = 2
            while label in provider_labels or label in reserved:
                label = f"{base} [{suffix}]"
                suffix += 1
            provider_labels[label] = index
            rows.append([{"text": label}])
        rows.append([{"text": MODEL_BACK_MAIN}])
        MODEL_SELECTION.update(provider=None, page=0, labels=provider_labels)
        header += "\nUse /menu to restore the primary keyboard."
        current_ref = _load_models_message_ref()
        result = None
        if not _edit_reply_picker(cfg, current_ref, header, rows, "Choose a model provider"):
            result = _send_reply_picker(cfg, header, rows)
        _remember_reply_picker_message(result)
        return
    provider = providers[provider_index]
    ACTIVE_PICKER = "models"
    items = groups[provider]
    pages = max(1, (len(items) + MODELS_PAGE_SIZE - 1) // MODELS_PAGE_SIZE)
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 0
    page = min(max(0, page), pages - 1)
    MODEL_PAGE_STATE.update(provider_index=provider_index, page=page)
    start = page * MODELS_PAGE_SIZE
    rows = []
    seen = {}
    labels = {}
    reserved = {MODEL_CLOSE, MODEL_BACK, MODEL_BACK_MAIN, MODEL_PREVIOUS, MODEL_NEXT,
                "Next", "Previous", "Sessions", "Models", "Help",
                "Current session", "Cancel", "Menu", "Show menu", "Files",
                "/menu", "/session", "/models", "/model", "/help"}
    for offset, model in enumerate(items[start:start + MODELS_PAGE_SIZE]):
        base = str(model.get("name") or model["id"]).replace("\n", " ").replace("\r", " ")[:28]
        seen[base] = seen.get(base, 0) + 1
        name = base if seen[base] == 1 else f"{base} [{start + offset + 1}]"
        if current and model["id"] == current:
            name = f"Current: {name}"
        name = name[:64]
        if name in labels or name in reserved:
            name = f"{base} [{start + offset + 1}]"[:64]
        while name in labels or name in reserved:
            name = f"{name[:56]} [{start + offset + 1}]"[:64]
        labels[name] = start + offset
        rows.append([{"text": name}])
    nav = []
    if page > 0:
        nav.append({"text": "Previous"})
    if page + 1 < pages:
        nav.append({"text": "Next"})
    if nav:
        rows.append(nav)
    rows.append([{"text": MODEL_BACK}, {"text": MODEL_CLOSE}])
    MODEL_SELECTION.update(provider=provider_index, page=page, labels=labels)
    MODEL_SELECTION["models"] = {
        name: (items[index].get("providerID"), items[index].get("id"))
        for name, index in labels.items()
    }
    text = f"<b>{_html_escape(provider)}</b> — Select a model ({page + 1}/{pages})"
    if current:
        text += f"\nCurrent model: <code>{_html_escape(current)}</code>"
    text += "\nUse /menu to restore the primary keyboard."
    current_ref = _load_models_message_ref()
    result = None
    if not _edit_reply_picker(cfg, current_ref, text, rows, "Choose a model"):
        result = _send_reply_picker(cfg, text, rows)
    _remember_reply_picker_message(result)


def _remember_reply_picker_message(result):
    message = result.get("result") if isinstance(result, dict) else None
    message_id = message.get("message_id") if isinstance(message, dict) else None
    chat_id = (message.get("chat") or {}).get("id") if isinstance(message, dict) else None
    if message_id and chat_id:
        _set_models_message_ref({"chat_id": chat_id, "message_id": message_id})


def _edit_reply_picker(cfg, message_ref, text, rows, placeholder):
    try:
        ref = json.loads(message_ref or "{}")
    except (TypeError, ValueError):
        return False
    chat_id, message_id = str(ref.get("chat_id") or ""), str(ref.get("message_id") or "")
    if not chat_id or not message_id:
        return False
    markup = json.dumps({
        "keyboard": rows, "resize_keyboard": True,
        "one_time_keyboard": True,
    }, ensure_ascii=False)
    try:
        api(cfg["TG_BOT_TOKEN"], "editMessageText", {
            "chat_id": chat_id, "message_id": message_id, "text": text,
            "parse_mode": "HTML",
        }, timeout=15)
        api(cfg["TG_BOT_TOKEN"], "editMessageReplyMarkup", {
            "chat_id": chat_id, "message_id": message_id,
            "reply_markup": markup,
        }, timeout=15)
        _set_models_message_ref({"chat_id": chat_id, "message_id": message_id})
        return True
    except Exception as e:
        log(f"[{ts()}] picker message edit failed; sending replacement: {e!r}", flush=True)
        try:
            api(cfg["TG_BOT_TOKEN"], "editMessageReplyMarkup", {
                "chat_id": chat_id, "message_id": message_id,
                "reply_markup": json.dumps({"inline_keyboard": []}),
            }, timeout=15)
        except Exception:
            pass
        return False


def _set_models_message_ref(ref):
    try:
        temp = MODELS_CACHE.with_name(f".models-message.{os.getpid()}.tmp")
        payload = json.dumps({"chat_id": str(ref["chat_id"]),
                              "message_id": str(ref["message_id"]),
                              "expires": int(time.time()) + 23 * 3600})
        temp.write_text(payload, encoding="utf-8")
        os.chmod(temp, 0o600)
        MODELS_CACHE.with_name("models-message.json").parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp, MODELS_CACHE.with_name("models-message.json"))
    except OSError as e:
        log(f"[{ts()}] could not save model-picker message reference: {e!r}", flush=True)


def _switch_session_model(cfg, model):
    sid, how = resolve_session(cfg)
    if not sid:
        send_text(cfg, "No active session is available for model switching.")
        return
    model_name = _html_escape(model.get("name") or model.get("id") or "model")
    provider = _html_escape(model.get("providerID") or "")
    session_name = _html_escape(session_title(_session_by_id(cfg, sid) or {"id": sid}))
    _opencode_api(
        cfg, "post", f"/api/session/{urllib.parse.quote(sid, safe='')}/model",
        {"model": {"id": model["id"], "providerID": model["providerID"]}}, timeout=30)
    log(f"[{ts()}] model switch sid={sid} ({how}) -> {model['providerID']}/{model['id']}", flush=True)
    _send_picker_notice(cfg, f"<b>Model switched</b>\n{model_name} (<code>{provider}</code>)\nSession: {session_name}")


def handle_callback(cfg, cb):
    """Handle inline-keyboard callbacks (legacy model messages only)."""
    data = str(cb.get("data") or "")
    callback_id = str(cb.get("id") or "")
    if callback_id:
        try:
            api(cfg["TG_BOT_TOKEN"], "answerCallbackQuery",
                {"callback_query_id": callback_id}, timeout=10)
        except Exception as e:
            log(f"[{ts()}] answerCallbackQuery failed: {e!r}", flush=True)
    message_ref = _callback_message_ref(cb)
    parts = data.split(":")
    try:
        if len(parts) == 3 and parts[1] == "p":
            _models_menu(cfg, provider_index=int(parts[2]), models_snapshot=_read_models_cache())
            return True
        if len(parts) == 4 and parts[1] == "l":
            _models_menu(cfg, int(parts[2]), int(parts[3]), models_snapshot=_read_models_cache())
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
                send_text(cfg, f"Model switch failed: {_html_escape(str(e)[:140])}", parse_mode="HTML")
            else:
                _invalidate_model_message_ref()
            return True
    except (TypeError, ValueError):
        return False
    return False


def handle_control_message(cfg, msg, text):
    """Handle Telegram keyboard commands before normal agent injection."""
    global SESSION_PAGE, SESSION_SNAPSHOT, ACTIVE_PICKER
    cmd = (text or "").strip().replace("\ufe0e", "").replace("\ufe0f", "").strip()
    if cmd.startswith("/") and "@" in cmd:
        cmd = cmd.split("@", 1)[0]
    if cmd == "/newsession":
        # Retired from the keyboard; ignore old buttons instead of starting a prompt.
        return True

    # Handle the name-entry state first so ordinary text is never mistaken for a
    # command and create-session actions can never become the title themselves.
    if ACTIVE_PICKER == "new-session-name":
        if cmd in ("Cancel", MODEL_CLOSE):
            _restore_primary_controls()
            send_text(cfg, "Session creation cancelled.")
            return True
        if cmd in ("/menu", "Menu", "Show menu"):
            _restore_primary_controls()
            _send_keyboard(cfg)
            return True
        if cmd in (NEW_SESSION, CREATE_SESSION):
            _begin_new_session(cfg)
            return True
        if cmd in ("Next", "Previous"):
            return True
        controls = {
            "/session", "Sessions", "/models", "/model", "Models", "/start",
            "/help", "Help", "/current", "Current session", "/files", "Files",
        }
        if cmd in controls:
            _restore_primary_controls()
            return handle_control_message(cfg, msg, cmd)
        if msg.get("photo") or msg.get("document"):
            send_text(cfg, "Send a text name for the session, or Cancel. Attachments are not accepted as names.")
            return True
        title = " ".join(cmd.split())
        if not title:
            send_text(cfg, "Session name cannot be empty. Send a name, or Cancel.")
            return True
        if title.startswith("/"):
            send_text(cfg, "That command is not a session name. Send a name, or Cancel.")
            return True
        if len(title) > SESSION_NAME_MAX_LENGTH:
            send_text(cfg, f"Session name is too long. Use {SESSION_NAME_MAX_LENGTH} characters or fewer.")
            _begin_new_session(cfg)
            return True
        try:
            session = create_session(cfg, title)
            if not _session_by_id(cfg, session["id"]):
                raise RuntimeError("The new session was created but could not be verified in the session list.")
            _set_active_session(session)
        except Exception as e:
            log(f"[{ts()}] session creation failed: {e!r}", flush=True)
            send_text(cfg, "Could not create the session. Check that OpenCode is running and try again.")
            _begin_new_session(cfg)
            return True
        _restore_primary_controls()
        send_text(cfg, f"<b>Session created and selected:</b> {_html_escape(session_title(session))}\n<b>Session ID:</b> <code>{_html_escape(session['id'])}</code>", parse_mode="HTML")
        return True

    # New-session actions work from the main keyboard and any active picker.
    if cmd in (NEW_SESSION, CREATE_SESSION):
        if ACTIVE_PICKER in ("models", "providers", "sessions"):
            _restore_primary_controls()
            _invalidate_model_message_ref()
        _begin_new_session(cfg)
        return True

    if cmd == "Cancel" and ACTIVE_PICKER == "sessions":
        _restore_primary_controls()
        _clear_session_picker(cfg)
        _send_keyboard(cfg, "Menu")
        return True
    if cmd == "Cancel" and ACTIVE_PICKER in ("providers", "models"):
        _restore_primary_controls()
        _invalidate_model_message_ref()
        _send_keyboard(cfg, "Menu")
        return True
    if cmd in ("Next", "Previous") and ACTIVE_PICKER == "sessions":
        if SESSION_SNAPSHOT:
            _send_session_picker(cfg, SESSION_PAGE + (1 if cmd == "Next" else -1), SESSION_SNAPSHOT)
        return True
    if cmd in ("Previous", "Next") and ACTIVE_PICKER in ("providers", "models"):
        if ACTIVE_PICKER == "models":
            provider_index = MODEL_SELECTION.get("provider")
            if provider_index is not None:
                page = MODEL_SELECTION.get("page", 0) + (1 if cmd == "Next" else -1)
                _models_menu(cfg, provider_index=provider_index, page=page,
                             models_snapshot=_read_models_cache())
        return True
    if cmd in ("/start", "/help", "Help"):
        if ACTIVE_PICKER is not None:
            _invalidate_model_message_ref()
        _restore_primary_controls()
        MODEL_PAGE_STATE.update(provider_index=None, page=0)
        MODEL_SELECTION.update(provider=None, page=0, labels={})
        SESSION_SNAPSHOT = []
        SESSION_PAGE = 0
        SESSION_BUTTONS.clear()
        ACTIVE_PICKER = None
        _send_keyboard(cfg, "<b>Commands</b>\n/session selects a session\n/current shows the active target\n/models switches its model\n/files lists received files\n\nSend any text to the active session. Agent replies arrive through <code>tg_send</code> and <code>tg_sendfile</code>.",
                       configure=(cmd == "/start"), parse_mode="HTML")
        return True
    if cmd in ("/files", "Files"):
        if ACTIVE_PICKER is not None:
            _invalidate_model_message_ref()
            _restore_primary_controls()
        sid, _ = resolve_session(cfg)
        directory = FILES / (sid if sid else "unassigned")
        entries = sorted((p for p in directory.iterdir() if p.is_file()),
                         key=lambda p: p.stat().st_mtime, reverse=True) if directory.exists() else []
        if not entries:
            send_text(cfg, "No files have been received for the active session.")
        else:
            send_text(cfg, "Files for this session:\n" + "\n".join(str(p) for p in entries[:20]))
        return True
    if cmd in ("/current", "Current session"):
        if ACTIVE_PICKER is not None:
            _invalidate_model_message_ref()
            _restore_primary_controls()
        sid, _ = resolve_session(cfg)
        session = _session_by_id(cfg, sid) if sid else None
        if session:
            send_text(cfg, f"<b>Active session:</b> {_html_escape(session_title(session))}\n<b>Session ID:</b> <code>{_html_escape(sid)}</code>", parse_mode="HTML")
        else:
            send_text(cfg, f"Active session: <code>{_html_escape(sid or 'not set')}</code>", parse_mode="HTML")
        return True
    if cmd in ("/session", "Sessions"):
        if ACTIVE_PICKER is not None:
            _invalidate_model_message_ref()
        _restore_primary_controls()
        MODEL_PAGE_STATE.update(provider_index=None, page=0)
        SESSION_PAGE = 0
        _send_session_picker(cfg)
        return True
    if cmd in ("/menu", "Menu", "Show menu"):
        _restore_primary_controls()
        _invalidate_model_message_ref()
        _clear_session_picker(cfg)
        _send_keyboard(cfg, "Menu")
        return True
    if cmd in ("/models", "/model", "Models"):
        if ACTIVE_PICKER is not None:
            _invalidate_model_message_ref()
        _restore_primary_controls()
        MODEL_SELECTION.update(provider=None, page=0, labels={})
        MODEL_PAGE_STATE.update(provider_index=None, page=0)
        SESSION_BUTTONS.clear()
        SESSION_SNAPSHOT = []
        _invalidate_model_message_ref()
        ACTIVE_PICKER = None
        _models_menu(cfg)
        return True
    if ACTIVE_PICKER == "sessions" and cmd in SESSION_BUTTONS:
        if msg.get("photo") or msg.get("document"):
            send_text(cfg, "Attachment was not delivered because this message selected a session. Send it again after selection.")
            return True
        selected_sid = SESSION_BUTTONS[cmd]
        session = next((s for s in SESSION_SNAPSHOT if str(s.get("id") or "") == selected_sid), None)
        if not session:
            send_text(cfg, "That session picker has expired. Open /session and choose again.")
            return True
        if not re.fullmatch(r"ses[0-9A-Za-z_-]{6,80}", selected_sid):
            send_text(cfg, "Invalid session ID; the target was not changed.")
            return True
        _set_active_session(session)
        SESSION_PAGE = 0
        ACTIVE_PICKER = None
        SESSION_BUTTONS.clear()
        MODEL_SELECTION.update(provider=None, page=0, labels={})
        _clear_session_picker(cfg)
        LAST_SESSION_LABELS.clear()
        _send_keyboard(cfg, f"Selected: {_html_escape(session_title(session))}", parse_mode="HTML")
        return True
    if ACTIVE_PICKER in ("models", "providers", "sessions") and (msg.get("photo") or msg.get("document")):
        send_text(cfg, "Attachment was not delivered because this message was a picker control. Send it again without a picker caption.")
        return True
    stale_session_label = (
        (ACTIVE_PICKER == "sessions" and re.fullmatch(r".+ \[[0-9A-Za-z_-]{6,80}\]", cmd))
        or (ACTIVE_PICKER is None and re.fullmatch(r".+ \[ses[0-9A-Za-z_-]{6,80}\]", cmd))
        or (ACTIVE_PICKER is None and cmd in LAST_SESSION_LABELS)
    )
    if stale_session_label:
        send_text(cfg, "That session picker has expired. Open /session and choose again.")
        return True
    if cmd == MODEL_BACK and ACTIVE_PICKER == "models":
        _models_menu(cfg, models_snapshot=_read_models_cache())
        return True
    if ACTIVE_PICKER in ("models", "providers") and cmd in (
            "Sessions", "Current session", "Help", "Files", "/session",
            "/current", "/help", "/files"):
        if cmd in ("Current session", "/current"):
            sid, _ = resolve_session(cfg)
            session = _session_by_id(cfg, sid) if sid else None
            if session:
                send_text(cfg, f"<b>Active session:</b> {_html_escape(session_title(session))}\n<b>Session ID:</b> <code>{_html_escape(sid)}</code>", parse_mode="HTML")
            else:
                send_text(cfg, f"Active session: <code>{_html_escape(sid or 'not set')}</code>", parse_mode="HTML")
            return True
        if cmd in ("Help", "/help"):
            send_text(cfg, "<b>Commands</b>\n/session selects a session\n/current shows the active target\n/models switches its model\n/files lists received files\n\nSend any text to the active session. Agent replies arrive through <code>tg_send</code> and <code>tg_sendfile</code>.", parse_mode="HTML")
            return True
        if cmd in ("Files", "/files"):
            sid, _ = resolve_session(cfg)
            directory = FILES / (sid if sid else "unassigned")
            entries = sorted((p for p in directory.iterdir() if p.is_file()),
                             key=lambda p: p.stat().st_mtime, reverse=True) if directory.exists() else []
            send_text(cfg, "No files have been received for the active session." if not entries else
                      "Files for this session:\n" + "\n".join(str(p) for p in entries[:20]))
            return True
        if cmd in ("Sessions", "/session"):
            SESSION_PAGE = 0
            SESSION_SNAPSHOT = []
            SESSION_BUTTONS.clear()
            _send_session_picker(cfg)
            return True
    if ACTIVE_PICKER in ("providers", "models") and cmd == MODEL_BACK_MAIN:
        _restore_primary_controls()
        _invalidate_model_message_ref()
        _send_keyboard(cfg, "Menu")
        return True
    if ACTIVE_PICKER == "providers" and cmd in ("Previous", MODEL_BACK, MODEL_CLOSE):
        return True
    selected_provider = MODEL_SELECTION.get("labels", {}).get(cmd)
    if ACTIVE_PICKER == "providers" and MODEL_SELECTION.get("provider") is None and selected_provider is not None:
        _models_menu(cfg, provider_index=selected_provider, page=0,
                     models_snapshot=_read_models_cache())
        return True
    groups = _group_models(_read_models_cache())
    providers = _ordered_providers(groups)
    if ACTIVE_PICKER == "models" and MODEL_SELECTION.get("provider") is not None:
        provider_index = MODEL_SELECTION["provider"]
        provider = providers[provider_index] if provider_index < len(providers) else None
        items = groups.get(provider, []) if provider else []
        index = MODEL_SELECTION.get("labels", {}).get(cmd)
        if index is not None and 0 <= index < len(items):
            displayed = MODEL_SELECTION.get("models", {}).get(cmd)
            if displayed != (items[index].get("providerID"), items[index].get("id")):
                send_text(cfg, "That model picker is out of date. Open /models and choose again.")
                return True
            try:
                _switch_session_model(cfg, items[index])
            except Exception as e:
                log(f"[{ts()}] model switch failed: {e!r}", flush=True)
                send_text(cfg, f"Model switch failed: {_html_escape(str(e)[:140])}", parse_mode="HTML")
            else:
                ACTIVE_PICKER = None
                MODEL_SELECTION.update(provider=None, page=0, labels={})
                _invalidate_model_message_ref()
            return True
    return False


def discover_session(cfg):
    """Newest non-archived root session (prefers this home directory)."""
    home = urllib.parse.quote(str(pathlib.Path.home()), safe="")
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


def _remove_pid_file():
    """Remove listener.pid only when it belongs to this process."""
    try:
        if PID.exists() and PID.read_text().strip() == str(os.getpid()):
            PID.unlink()
    except (OSError, ValueError):
        pass


def _install_listener_cleanup():
    atexit.register(_remove_pid_file)

    def _stop(_signum, _frame):
        raise SystemExit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _stop)
        except (ValueError, OSError):
            pass


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
    _send_keyboard(cfg, configure=True)
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
        params = {"chat_id": cfg["TG_CHAT_ID"], "text": chunk,
                  "disable_web_page_preview": "true"}
        if parse_mode:
            params["parse_mode"] = parse_mode
        try:
            res = api(cfg["TG_BOT_TOKEN"], "sendMessage", params, timeout=30)
        except Exception as e:
            if not parse_mode:
                raise
            log(f"[{ts()}] formatted Telegram message failed; retrying as plain text: {e!r}", flush=True)
            params["text"] = _plain_fallback(chunk)
            params.pop("parse_mode", None)
            res = api(cfg["TG_BOT_TOKEN"], "sendMessage", params, timeout=30)
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


USAGE = ("usage: telecode {menu|setup|listen|read|wait SECONDS|send TEXT|"
         "sendfile PATH [CAPTION]|status|get-id|--enable|--configure-cli}")


def cmd_help():
    print(USAGE)
    print()
    print("Run telecode with no arguments for the interactive menu.")
    print("Documentation: https://github.com/Aetherdz/telecode#readme")
    return 0


def cmd_setup():
    """Run the guided installer from the current checkout."""
    script = pathlib.Path(__file__).resolve().parent / "install.sh"
    if not script.is_file():
        print("installer not found; use the release install.sh", file=sys.stderr)
        return 2
    return subprocess.call(["bash", str(script)])


def cmd_configure_cli():
    """Run only the MCP registration step from the installer."""
    script = pathlib.Path(__file__).resolve().parent / "install.sh"
    if not script.is_file():
        print("installer not found; use the release install.sh", file=sys.stderr)
        return 2
    return subprocess.call(["bash", str(script), "--configure-cli"])


def cmd_menu():
    """Small Setup/Exit menu used when telecode runs without arguments."""
    options = [
        ("Full setup (MCP registration, credentials, startup)", cmd_setup),
        ("Configure a coding-agent CLI only", cmd_configure_cli),
        ("Enable login service (systemd)", cmd_install),
        ("Show status", cmd_status),
        ("Run the listener in this terminal", cmd_listen),
        ("Show help", cmd_help),
    ]
    while True:
        print()
        print("TeleCode - Telegram bridge for coding-agent sessions")
        print()
        for index, (label, _) in enumerate(options, 1):
            print(f"  {index}. {label}")
        print("  q. Exit")
        try:
            choice = input("\nSelect an option: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice in ("q", "quit", "exit", ""):
            return 0
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1][1]() or 0
        print("Choose a listed number, or q to exit.")


def cmd_install():
    """Install the current checkout as a user-level systemd service."""
    source = pathlib.Path(__file__).resolve().parent
    script = source / "install.sh"
    if not script.is_file():
        print("installer not found; use the release install.sh", file=sys.stderr)
        return 2
    return subprocess.call(["bash", str(script), "--enable"])


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "get-id":
        helper = pathlib.Path(__file__).resolve().with_name("get_telegram_id.py")
        if not helper.is_file():
            print("chat ID helper is not installed; reinstall TeleCode", file=sys.stderr)
            return 2
        return subprocess.call([sys.executable, str(helper)])
    if len(sys.argv) > 1 and sys.argv[1] == "--init":
        return subprocess.call(["bash", str(pathlib.Path(__file__).resolve().parent / "install.sh")])
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        return subprocess.call(["bash", str(pathlib.Path(__file__).resolve().parent / "install.sh")])
    if len(sys.argv) > 1 and sys.argv[1] in ("--enable", "--configure-cli"):
        args = ["bash", str(pathlib.Path(__file__).resolve().parent / "install.sh"), sys.argv[1]]
        return subprocess.call(args)
    cmds = {
        "menu": cmd_menu, "help": cmd_help, "listen": cmd_listen,
        "read": cmd_read, "wait": cmd_wait, "send": cmd_send,
        "sendfile": cmd_sendfile, "status": cmd_status,
    }
    if len(sys.argv) < 2:
        if sys.stdin.isatty() and sys.stdout.isatty():
            return cmd_menu()
        print(USAGE, file=sys.stderr)
        return 2
    if sys.argv[1] not in cmds:
        print(USAGE, file=sys.stderr)
        return 2
    return cmds[sys.argv[1]]() or 0


if __name__ == "__main__":
    sys.exit(main())
