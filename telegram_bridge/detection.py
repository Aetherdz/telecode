"""Privacy-preserving discovery data for the browser setup wizard.

Only client availability and a small amount of session metadata is returned; no
transcript or prompt content is read or exposed.
"""
from __future__ import annotations

import os
import pathlib
import shutil

import setup_cli

MAX_SESSIONS = 3
MAX_METADATA_BYTES = 64 * 1024
_CARDS = (
    ("opencode", "OpenCode", "targeted-verified"),
    ("claude", "Claude Code", "targeted-verified"),
    ("codex", "Codex CLI", "targeted-experimental"),
    ("cursor", "Cursor", "targeted-experimental"),
    ("gemini", "Gemini CLI", "outbound"),
    ("cline", "Cline", "outbound"),
    ("roo", "Roo Code", "outbound"),
    ("q", "Amazon Q Developer", "outbound"),
    ("manual", "Other MCP client", "manual"),
)


def cards():
    """Return exactly nine cards, separating verified detection from instructions."""
    hosts = {host[1]: host for host in setup_cli.HOSTS if host[1] is not None}
    result = []
    for key, name, capability in _CARDS:
        if key == "manual":
            result.append({"key": key, "name": name, "detected": False,
                           "capability": capability, "verified": False})
            continue
        host = hosts[key]
        executable, config, supported = setup_cli.discover(host)
        result.append({"key": key, "name": name,
                       "detected": bool(executable or config),
                       "capability": capability if supported else "manual",
                       "verified": capability == "targeted-verified" and supported,
                       "evidence": {"executable": bool(executable), "config": bool(config)}})
    return result


def _inside_home(path, home):
    try:
        return pathlib.Path(path).resolve(strict=True).is_relative_to(home)
    except (OSError, RuntimeError):
        return False


def browse_directories(home=None):
    """List immediate home directories only; reject links and escaping entries."""
    root = pathlib.Path(home or pathlib.Path.home()).resolve()
    if not root.is_dir():
        return []
    found = []
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name.casefold())
    except OSError:
        return []
    for child in children:
        try:
            if child.is_symlink() or not child.is_dir() or not _inside_home(child, root):
                continue
            # Validate structure without opening files or enumerating contents.
            if not child.name or child.name in (".", ".."):
                continue
            found.append({"name": child.name, "path": str(child)})
        except OSError:
            continue
    return found


def recent_sessions(home=None):
    """Expose at most three session metadata summaries, never transcript text."""
    root = pathlib.Path(home or pathlib.Path.home()).resolve()
    candidates = []
    # OpenCode stores session metadata in its state DB; discovery is intentionally
    # limited to metadata JSON files when present, not message/transcript files.
    metadata_roots = (root / ".local/share/opencode/storage/session",)
    for directory in metadata_roots:
        if not _inside_home(directory, root) or not directory.is_dir():
            continue
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)[:500]
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink() or not entry.is_file() or entry.suffix != ".json":
                    continue
                if entry.stat().st_size > MAX_METADATA_BYTES or not _inside_home(entry, root):
                    continue
                import json
                # Read at most the advertised limit even if the file grows after stat.
                with entry.open("rb") as stream:
                    raw = stream.read(MAX_METADATA_BYTES + 1)
                if len(raw) > MAX_METADATA_BYTES:
                    continue
                data = json.loads(raw.decode("utf-8"))
                if not isinstance(data, dict):
                    continue
                candidates.append({"id": str(data.get("id", ""))[:100],
                                   "title": str(data.get("title", "Untitled"))[:120],
                                   "directory": str(data.get("directory", ""))[:300],
                                   "updated": data.get("time", {}).get("updated", 0)
                                   if isinstance(data.get("time"), dict) else 0})
            except (OSError, ValueError, TypeError):
                continue
    candidates.sort(key=lambda item: item["updated"] if isinstance(item["updated"], (int, float)) else 0, reverse=True)
    # Summaries are metadata-only; mask values that resemble credentials and do not
    # return arbitrary metadata strings verbatim.
    secret = __import__("re").compile(r"(?i)(token|secret|password|api[_-]?key)\s*[:=]\s*\S+")
    for item in candidates:
        for key in ("id", "title", "directory"):
            item[key] = secret.sub(r"\1=[REDACTED]", item[key])
    return candidates[:MAX_SESSIONS]
