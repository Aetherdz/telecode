"""Shared helpers: logging, env loading, Bot API transport, inbox cursor."""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import telegram_bridge as tg


def ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(msg, **kwargs):
    """Diagnostics go to stderr (stdout stays clean for command output / MCP)."""
    kwargs.pop("flush", None)
    print(msg, file=sys.stderr, flush=True, **kwargs)


def load_env():
    cfg = {}
    if not tg.ENV.is_file():
        raise FileNotFoundError(f"missing private Telegram config: {tg.ENV}")
    if tg.ENV.is_symlink():
        raise PermissionError("telegram.env must not be a symlink")
    metadata = tg.ENV.stat()
    if metadata.st_mode & 0o077:
        raise PermissionError("telegram.env permissions must be 0600")
    if os.name != "nt" and metadata.st_uid != os.getuid():
        raise PermissionError("telegram.env must be owned by the current user")
    for line in tg.ENV.read_text(encoding="utf-8").splitlines():
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


def _updated(s: dict) -> float:
    return float(((s.get("time") or {}).get("updated")) or 0)


def _html_escape(value):
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _plain_fallback(value):
    value = re.sub(r"</?(?:b|strong|i|em|u|s|strike|del|code|pre|a|blockquote)(?:\s+[^>]*)?>", "", str(value), flags=re.I)
    return (value.replace("&amp;", "&").replace("&lt;", "<")
            .replace("&gt;", ">"))


def _cursor():
    return int(tg.CURSOR.read_text().strip()) if tg.CURSOR.exists() else 0


def _unread():
    cur = tg._cursor()
    out = []
    if tg.INBOX.exists():
        for line in tg.INBOX.read_text(encoding="utf-8").splitlines():
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
        tg.CURSOR.write_text(str(max(int(r["update_id"]) for r in recs)))
