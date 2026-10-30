#!/usr/bin/env python3
"""Telegram bridge — MCP stdio server for OpenCode.

Exposes the owner-chat tools (send / sendfile / read / status) to the agent in
every session. Registered in ~/.config/opencode/opencode.json
(mcp.servers.telegram).

- Spawned by OpenCode on session start; ensures the listener daemon is running.
- Protocol: MCP stdio (newline-delimited JSON-RPC 2.0). stdout is protocol-only;
  logs go to stderr.
"""
import json
import os
import pathlib
import subprocess
import sys
import time

BASE = pathlib.Path(os.environ.get(
    "TELEGRAM_BRIDGE_HOME", str(pathlib.Path(os.environ.get("XDG_CONFIG_HOME", pathlib.Path.home() / ".config")) / "telegram-bridge")
)).expanduser().resolve()
CODE_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_DIR))
import tg_bridge as tb  # noqa: E402  (stdlib-only module, main-guarded)
import telegram_bridge
telegram_bridge.state.configure(str(BASE))

SERVER_INFO = {"name": "telegram-bridge", "version": "1.0.0"}
PROTOCOL_FALLBACK = "2025-06-18"


def log(msg):
    print(f"[tg-mcp {time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def ensure_listener():
    """Idempotent: make sure the telegram listener daemon is running."""
    try:
        cfg = tb.load_env()
        tb.start_opencode_listener(cfg)
        return
    except Exception as e:
        log(f"listener auto-start failed: {e!r}")


TOOLS = [
    {
        "name": "tg_send",
        "description": "Send a Telegram message to the owner chat.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Message text."}},
            "required": ["text"],
        },
    },
    {
        "name": "tg_sendfile",
        "description": "Send a file from an explicitly allowlisted local output directory to the owner chat.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path under TG_SEND_ROOTS."},
                "caption": {"type": "string", "description": "Optional caption."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "tg_read",
        "description": (
            "Read a bounded list of owner messages from the inbox if needed. "
            "Replies and requested files should be delivered to the owner with tg_send/tg_sendfile."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Max messages (default 20)."}},
        },
    },
    {
        "name": "tg_status",
        "description": (
            "Show Telegram bridge status: bot identity, listener daemon, inject "
            "target session, delivery mode, unread count."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "tg_sessions",
        "description": "List recent OpenCode sessions available for Telegram routing. Use /session in Telegram for the on-screen chooser.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "tg_select_session",
        "description": "Select an OpenCode session as the sole Telegram message target.",
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string", "description": "Exact session ID."}},
            "required": ["session_id"],
        },
    },
    {
        "name": "tg_open_session_picker",
        "description": "Send the session chooser keyboard to the configured Telegram owner chat.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _h_send(args):
    cfg = tb.load_env()
    text = str(args.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")
    mid = tb.send_text(cfg, text)
    return f"sent ok (message_id={mid})"


def _h_sendfile(args):
    raw = str(args.get("path") or "").strip()
    if not raw:
        raise ValueError("path is required")
    path = pathlib.Path(os.path.expanduser(raw))
    original_path = path
    try:
        path = path.resolve(strict=True)
    except OSError:
        raise ValueError("no such file") from None
    if not path.is_file() or original_path.is_symlink():
        raise ValueError(f"no such file: {path}")
    cfg = None
    roots_spec = os.environ.get("TG_SEND_ROOTS", "")
    if not roots_spec.strip():
        cfg = tb.load_env()
        roots_spec = str(cfg.get("TG_SEND_ROOTS", ""))
    allowed = roots_spec.split(os.pathsep)
    roots = [pathlib.Path(os.path.expanduser(p)).resolve() for p in allowed if p.strip()]
    if not roots or not any(path == root or root in path.parents for root in roots):
        raise ValueError("file is outside configured TG_SEND_ROOTS allowlist")
    forbidden = [tb.ENV.resolve(), pathlib.Path.home() / ".ssh",
                 pathlib.Path.home() / ".config" / "opencode"]
    if path == tb.ENV.resolve() or any(root in path.parents for root in forbidden[1:]):
        raise ValueError("sensitive file paths are never sendable")
    if path.stat().st_size > 49 * 1024 * 1024:
        raise ValueError("file too large for Telegram (limit ~50MB)")
    if cfg is None:
        cfg = tb.load_env()
    mid = tb.send_file(cfg, path, str(args.get("caption") or ""))
    return f"sent file ok (message_id={mid})"


def _h_read(args):
    limit = max(1, min(int(args.get("limit") or 20), 100))
    recs = tb._unread()
    shown = recs[: max(0, limit)]
    out = []
    for r in shown:
        item = {"iso": r.get("iso"), "text": r.get("text")}
        if r.get("file"):
            item["file"] = r["file"]
        out.append(item)
    if shown:
        tb._advance(shown)
    return json.dumps(out, ensure_ascii=False)


def _h_status(args):
    cfg = tb.load_env()
    out = []
    try:
        me = tb.api(cfg["TG_BOT_TOKEN"], "getMe", timeout=15)
        bot = me.get("result") or {}
        out.append(f"bot: @{bot.get('username')} (id {bot.get('id')})")
    except Exception as e:
        out.append(f"bot: error {e!r}")
    alive = "down"
    if tb.PID.exists():
        try:
            pid = tb.PID.read_text().strip()
            os.kill(int(pid), 0)
            alive = f"up (pid {pid})"
        except Exception:
            alive = "stale pid"
    out.append(f"listener: {alive}")
    sid, how = tb.resolve_session(cfg)
    out.append(f"inject target: {sid or '(none)'} [{how}]")
    out.append(
        f"delivery: {cfg.get('TG_DELIVERY') or 'steer'}; unread: {len(tb._unread())}"
    )
    return "\n".join(out)


def _h_sessions(args):
    cfg = tb.load_env()
    sessions = tb.list_sessions(cfg)
    active, _ = tb.resolve_session(cfg)
    return json.dumps([{"id": s.get("id"), "title": s.get("title") or "Untitled",
                        "directory": s.get("directory") or "",
                        "active": str(s.get("id")) == active}
                       for s in sessions], ensure_ascii=False)


def _h_open_session_picker(args):
    cfg = tb.load_env()
    tb._send_session_picker(cfg)
    return "session picker sent to Telegram"


def _h_select_session(args):
    cfg = tb.load_env()
    sid = str(args.get("session_id") or "")
    session = tb._session_by_id(cfg, sid)
    if not session:
        raise ValueError("session not found in the current home directory")
    tb._set_active_session(session)
    return f"active Telegram target set to {tb.session_label(session)} (ID: {sid})"


HANDLERS = {
    "tg_send": _h_send,
    "tg_sendfile": _h_sendfile,
    "tg_read": _h_read,
    "tg_status": _h_status,
    "tg_sessions": _h_sessions,
    "tg_select_session": _h_select_session,
    "tg_open_session_picker": _h_open_session_picker,
}


SUPPORTED_PROTOCOLS = ("2025-06-18",)


def _send(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def _dispatch(req, initialized):
    """Handle one JSON-RPC message; returns the response dict or None."""
    if not isinstance(req, dict):
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "invalid request"}}
    mid = req.get("id")
    method = req.get("method")
    if method == "initialize":
        params = req.get("params") or {}
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOLS else PROTOCOL_FALLBACK
        return {"jsonrpc": "2.0", "id": mid,
                "result": {"protocolVersion": version,
                           "capabilities": {"tools": {}},
                           "serverInfo": SERVER_INFO}}
    if method in ("notifications/initialized", "notifications/cancelled",
                  "notifications/progress", "notifications/roots/list_changed"):
        return None
    if not initialized:
        if mid is None:
            return None
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32002, "message": "server not initialized"}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = HANDLERS.get(name) if isinstance(name, str) else None
        if fn is None:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": f"unknown tool: {name}"}}
        try:
            text = fn(args if isinstance(args, dict) else {})
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": f"error: {e}"}],
                               "isError": True}}
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main():
    ensure_listener()
    log("server up")
    initialized = False
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except Exception:
            _send({"jsonrpc": "2.0", "id": None,
                   "error": {"code": -32700, "message": "parse error"}})
            continue
        if isinstance(msg, list):  # JSON-RPC batch: unsupported (MCP >= 2025-03-26)
            _send({"jsonrpc": "2.0", "id": None,
                   "error": {"code": -32600, "message": "batch requests are not supported"}})
            continue
        if isinstance(msg, dict) and msg.get("method") == "initialize":
            initialized = True
        resp = _dispatch(msg, initialized)
        if resp is not None:
            _send(resp)
    log("stdin closed; exiting")


if __name__ == "__main__":
    main()
