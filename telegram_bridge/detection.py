"""Privacy-conscious local session metadata and directory discovery."""
from __future__ import annotations

import json
import datetime
import pathlib
import re

import setup_cli

MAX_SESSIONS = 3
MAX_METADATA_BYTES = 64 * 1024
HOME = pathlib.Path.home()
CARDS = (
    ("opencode", "OpenCode", "inbound", (".local/share/opencode/storage/session",)),
    ("claude", "Claude Code", "inbound", (".claude/projects",)),
    ("codex", "Codex CLI", "outbound", (".codex/sessions",)),
    ("cursor", "Cursor", "outbound", (".cursor",)),
    ("gemini", "Gemini CLI", "outbound", (".gemini",)),
    ("cline", "Cline", "outbound", (".vscode/globalStorage/saoudrizwan.claude-dev",)),
    ("roo", "Roo Code", "outbound", (".vscode/globalStorage/rooveterinaryinc.roo-cline",)),
    ("q", "Amazon Q", "outbound", (".aws/amazonq",)),
    ("manual", "Other MCP client", "manual", ()),
)
_SECRET = re.compile(r"(?i)(token|secret|password|api[_-]?key)\s*[:=]\s*\S+")


def mask_chat_id(value):
    text = str(value)
    return "••••" + text[-4:] if len(text) > 4 else "••••"


def _home(home=None):
    return pathlib.Path(home or pathlib.Path.home()).expanduser().resolve()


def _safe(path, home):
    raw = pathlib.Path(path).expanduser()
    if not raw.is_absolute():
        raise ValueError("absolute path required")
    if ".." in raw.parts:
        raise ValueError("parent traversal is not allowed")
    resolved = raw.resolve(strict=True)
    if not resolved.is_relative_to(home):
        raise ValueError("path outside home")
    return resolved


def cards():
    hosts = {host[1]: host for host in setup_cli.HOSTS if host[1]}
    result = []
    for key, name, capability, paths in CARDS:
        host = hosts.get(key)
        found_cli, config, _supported = setup_cli.discover(host) if host else (False, None, False)
        result.append({"key": key, "name": name, "capability": capability,
                       "detected": bool(found_cli or config), "config_path": str(config or ""),
                       "session_paths": [str(HOME / part) for part in paths],
                       "verified": key == "opencode", "needs_manual": key != "opencode",
                       "sessions": []})
    return result


def clients(setup_module=None):
    """Legacy client registry shape retained for the existing web endpoint."""
    return [{"name": item["name"], "key": item["key"], "detected": item["detected"],
             "supported": item["capability"] in ("inbound", "outbound"),
             "config": item["config_path"]} for item in cards() if item["key"] != "manual"]


def browse(path=None, home=None):
    root = _home(home)
    target = _safe(path or root, root)
    if not target.is_dir():
        raise ValueError("not a directory")
    entries = []
    for child in sorted(target.iterdir(), key=lambda item: item.name.casefold())[:200]:
        try:
            if child.is_symlink() or not child.is_dir():
                continue
            safe_child = _safe(child, root)
            entries.append({"name": safe_child.name, "path": str(safe_child)})
        except (OSError, ValueError, RuntimeError):
            continue
    parent = str(target.parent) if target != root else None
    return {"ok": True, "path": str(target), "parent": parent, "entries": entries}


def browse_directories(home=None):
    return browse(home=home)["entries"]


def _metadata_file(path):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_METADATA_BYTES:
            return None
        with path.open("rb") as stream:
            raw = stream.read(MAX_METADATA_BYTES + 1)
        if len(raw) > MAX_METADATA_BYTES:
            return None
        obj = json.loads(raw.decode("utf-8"))
        if not isinstance(obj, dict):
            return None
        session_id = str(obj.get("id") or path.stem)[:120]
        title = str(obj.get("title") or session_id)[:160]
        time_data = obj.get("time") if isinstance(obj.get("time"), dict) else {}
        raw_date = time_data.get("updated") or time_data.get("created") or ""
        if isinstance(raw_date, (int, float)):
            date = datetime.datetime.fromtimestamp(raw_date / (1000 if raw_date > 10_000_000_000 else 1), datetime.timezone.utc).isoformat()
        else:
            date = str(raw_date)[:40]
        return {"id": _SECRET.sub(r"\1=[REDACTED]", session_id),
                "title": _SECRET.sub(r"\1=[REDACTED]", title), "date": date}
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def detect(agent_key, path=None, home=None):
    root = _home(home)
    row = next((item for item in CARDS if item[0] == agent_key), None)
    if row is None or agent_key == "manual":
        return {"ok": False, "path": "", "count": 0, "sessions": [], "needs_path": True,
                "verified": False, "error": "Choose a supported session folder manually."}
    if path:
        target = _safe(path, root)
        if agent_key != "opencode":
            return {"ok": False, "path": str(target), "count": 0, "sessions": [], "needs_path": True,
                    "verified": False, "error": "This agent's session format is not verified; manual configuration is required."}
        if not validate(agent_key, target, root):
            return {"ok": False, "path": str(target), "count": 0, "sessions": [], "needs_path": True,
                    "verified": agent_key == "opencode", "error": "Folder does not match a known session structure."}
    else:
        target = None
        if agent_key == "opencode":
            candidate = root / ".local/share/opencode/storage/session"
            if validate(agent_key, candidate, root):
                target = candidate
        if target is None:
            return {"ok": False, "path": "", "count": 0, "sessions": [], "needs_path": True,
                    "verified": agent_key == "opencode", "error": "Session storage was not verified. Select a folder to inspect."}
    files = []
    try:
        for item in target.iterdir():
            if item.is_file() and item.suffix in (".json", ".jsonl") and not item.is_symlink():
                files.append(item)
            elif item.is_dir() and not item.is_symlink():
                try:
                    files.extend(child for child in list(item.iterdir())[:200]
                                 if child.is_file() and child.suffix in (".json", ".jsonl") and not child.is_symlink())
                except OSError:
                    continue
            if len(files) >= 500:
                break
    except OSError:
        return {"ok": False, "path": str(target), "count": 0, "sessions": [], "needs_path": True,
                "verified": agent_key == "opencode", "error": "Cannot read session metadata."}
    metadata = [data for file in files[:500] if (data := _metadata_file(file)) is not None]
    metadata.sort(key=lambda item: item["date"], reverse=True)
    return {"ok": True, "path": str(target), "count": len(metadata), "sessions": metadata[:MAX_SESSIONS],
            "needs_path": False, "verified": agent_key == "opencode"}


def recent_sessions(home=None):
    result = detect("opencode", home=home)
    return result["sessions"]


def validate(agent_key, path, home=None):
    root = _home(home)
    try:
        target = _safe(path, root)
    except (ValueError, OSError, RuntimeError):
        return False
    if not target.is_dir():
        return False
    if agent_key == "opencode":
        return any(p.is_file() and p.suffix == ".json" and not p.is_symlink() for p in target.iterdir())
    return False
