"""Pure Telegram Bot API transport: keyboards, sends, edits, downloads."""
import json
import os
import secrets
import time
import urllib.request

import telegram_bridge as tg


_BUTTON_STYLES = {
    "Cancel": "danger",
    "Help": "danger",
    "Current session": "success",
    "New session": "success",
    "Create session": "success",
    "Open by ID": "primary",
    "Sessions": "primary",
    "Models": "primary",
    "Previous": "primary",
    "Next": "primary",
    "Back": "primary",
    "Back to providers": "primary",
}


def _style_keyboard(rows):
    """Apply Bot API button styles to known controls, preserving all other data."""
    styled = []
    for row in rows:
        styled_row = []
        for button in row:
            if isinstance(button, dict):
                button = dict(button)
                style = _BUTTON_STYLES.get(str(button.get("text") or ""))
                if style:
                    button["style"] = style
            styled_row.append(button)
        styled.append(styled_row)
    return styled


def _download_file(token, file_id, name, destination=None):
    """Fetch a Telegram document/photo into the selected session folder."""
    try:
        fr = tg.api(token, "getFile", {"file_id": file_id}, timeout=60)
        fp = (fr.get("result") or {}).get("file_path")
        if not fp:
            return ""
        destination = destination or tg.FILES
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
        tg.log(f"[{tg.ts()}] file download failed: {e!r}", flush=True)
        return ""


def _keyboard(cfg):
    rows = [[{"text": "Current session"}, {"text": "New session"}],
            [{"text": "Models"}, {"text": "Sessions"}],
            [{"text": "Help"}]]
    return {"keyboard": tg._style_keyboard(rows),
            "resize_keyboard": True, "one_time_keyboard": False}


def _configure_commands(cfg):
    try:
        tg.api(cfg["TG_BOT_TOKEN"], "setMyCommands", {"commands": json.dumps([
            {"command": "menu", "description": "Show the TeleCode keyboard"},
            {"command": "session", "description": "Choose the active session"},
            {"command": "newsession", "description": "Create and select a session"},
            {"command": "models", "description": "Choose a model"},
            {"command": "model", "description": "Choose a model"},
            {"command": "current", "description": "Show the active session"},
            {"command": "files", "description": "List received files"},
            {"command": "start", "description": "Show TeleCode controls"},
            {"command": "help", "description": "Show available commands"},
        ])}, timeout=15)
    except Exception as e:
        tg.log(f"[{tg.ts()}] bot command menu setup failed: {e!r}", flush=True)


def _send_keyboard(cfg, text="TeleCode is ready. Select a session, then send a message.", *, configure=False):
    try:
        if configure:
            tg._configure_commands(cfg)
        tg.api(cfg["TG_BOT_TOKEN"], "sendMessage", {
            "chat_id": cfg["TG_CHAT_ID"],
            "text": text,
            "reply_markup": json.dumps(tg._keyboard(cfg), ensure_ascii=False)}, timeout=15)
    except Exception as e:
        tg.log(f"[{tg.ts()}] keyboard setup failed: {e!r}", flush=True)


def _send_inline(cfg, text, rows):
    params = {
        "chat_id": cfg["TG_CHAT_ID"], "text": text, "parse_mode": "HTML",
        "reply_markup": json.dumps({"inline_keyboard": tg._style_keyboard(rows)}, ensure_ascii=False),
    }
    try:
        return tg.api(cfg["TG_BOT_TOKEN"], "sendMessage", params, timeout=15)
    except Exception as e:
        tg.log(f"[{tg.ts()}] formatted inline message failed; retrying as plain text: {e!r}", flush=True)
        params["text"] = tg._plain_fallback(text)
        params.pop("parse_mode", None)
        return tg.api(cfg["TG_BOT_TOKEN"], "sendMessage", params, timeout=15)


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
        "reply_markup": json.dumps({"inline_keyboard": tg._style_keyboard(rows)}, ensure_ascii=False),
    }
    try:
        result = tg.api(cfg["TG_BOT_TOKEN"], "editMessageText", params, timeout=15)
    except Exception as e:
        tg.log(f"[{tg.ts()}] formatted model-menu edit failed; retrying as plain text: {e!r}", flush=True)
        params["text"] = tg._plain_fallback(text)
        params.pop("parse_mode", None)
        try:
            result = tg.api(cfg["TG_BOT_TOKEN"], "editMessageText", params, timeout=15)
        except Exception as fallback_error:
            tg.log(f"[{tg.ts()}] model-menu edit fallback failed: {fallback_error!r}", flush=True)
            return False
    return bool(result and result.get("ok", True))


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
            res = tg.api(cfg["TG_BOT_TOKEN"], "sendMessage", params, timeout=30)
        except Exception as e:
            if not parse_mode:
                raise
            tg.log(f"[{tg.ts()}] formatted Telegram message failed; retrying as plain text: {e!r}", flush=True)
            params["text"] = tg._plain_fallback(chunk)
            params.pop("parse_mode", None)
            res = tg.api(cfg["TG_BOT_TOKEN"], "sendMessage", params, timeout=30)
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
