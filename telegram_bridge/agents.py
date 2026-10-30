"""OpenCode session operations: creation, listing, discovery, targeting."""
import json
import os
import pathlib
import re
import shutil
import subprocess
import urllib.parse

import telegram_bridge as tg


def _agent_name(cfg):
    configured = (cfg.get("TELECODE_AGENT") or "").strip().lower()
    if configured:
        return configured
    # Keep explicit configuration authoritative, but make Cursor work out of
    # the box for installs that have Cursor Agent and no TELECODE_AGENT entry.
    return "cursor" if shutil.which((cfg.get("CURSOR_AGENT_BIN") or "agent").strip()) else "opencode"


def _codex_adapter(cfg):
    from adapters.codex import CodexAdapter
    try:
        active = json.loads(tg.ACTIVE_SESSION.read_text(encoding="utf-8"))
        model = active.get("model") if active.get("id") == tg._active_session_id() else None
        model_provider = active.get("modelProvider") if active.get("id") == tg._active_session_id() else None
    except (OSError, ValueError, TypeError):
        model = None
        model_provider = None
    return CodexAdapter(binary=(cfg.get("CODEX_BIN") or "codex").strip(),
                        model=model, model_provider=model_provider,
                        workspace=cfg.get("CODEX_WORKSPACE"))


def _agent_adapter(cfg):
    """Create the configured inbound adapter; OpenCode remains the default."""
    name = tg._agent_name(cfg)
    if name == "codex":
        return tg._codex_adapter(cfg)
    if name in ("claude-code", "claude"):
        from adapters.claude_code import ClaudeCodeAdapter
        return ClaudeCodeAdapter(binary=(cfg.get("CLAUDE_CODE_BIN") or "claude").strip())
    if name == "cursor":
        from adapters.cursor import CursorAdapter
        try:
            active = json.loads(tg.ACTIVE_SESSION.read_text(encoding="utf-8"))
            model = active.get("model") if active.get("id") == tg._active_session_id() else None
        except (OSError, ValueError, TypeError):
            model = None
        return CursorAdapter(
            binary=(cfg.get("CURSOR_AGENT_BIN") or "agent").strip(),
            workspace=cfg.get("CURSOR_WORKSPACE"),
            model=model,
        )
    from adapters.opencode import OpenCodeAdapter
    return OpenCodeAdapter(binary=tg._opencode_bin(cfg))


def _opencode_bin(cfg) -> str:
    explicit = (cfg.get("OPENCODE_BIN") or "").strip()
    if explicit:
        return explicit
    local = pathlib.Path.home() / ".opencode" / "bin" / "opencode"
    return str(local) if local.exists() else "opencode"


def _opencode_api(cfg, method, path, body=None, timeout=60):
    """Call the OpenCode HTTP API via the CLI; returns parsed JSON."""
    cmd = [tg._opencode_bin(cfg), "api", method, path]
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
    if len(title) > tg.SESSION_NAME_MAX_LENGTH:
        raise ValueError(f"Session name must be {tg.SESSION_NAME_MAX_LENGTH} characters or fewer.")
    if tg._agent_name(cfg) in ("cursor", "codex"):
        session = tg._agent_adapter(cfg).create_session(title)
        return {"id": session.id, "title": session.title,
                "directory": session.directory, "agent": session.agent}
    result = tg._opencode_api(
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


def _session_items(cfg, query: str):
    data = tg._opencode_api(
        cfg, "get", f"/api/session?order=desc&limit=1000&parentID=null{query}", timeout=30
    )
    if isinstance(data, dict):
        return data.get("data") or []
    return data or []


def list_sessions(cfg):
    """Return non-archived root sessions visible in the configured agent."""
    if tg._agent_name(cfg) == "codex":
        try:
            return [{"id": s.id, "title": s.title, "directory": s.directory,
                     "time": {"updated": s.updated}, "agent": s.agent}
                    for s in tg._codex_adapter(cfg).list_sessions()]
        except Exception as e:
            tg.log(f"[{tg.ts()}] Codex session listing failed: {e!r}", flush=True)
            return []
    if tg._agent_name(cfg) in ("claude-code", "claude"):
        try:
            return [{"id": s.id, "title": s.title, "directory": s.directory,
                     "time": {"updated": s.updated}, "agent": s.agent}
                    for s in tg._agent_adapter(cfg).list_sessions()]
        except Exception as e:
            tg.log(f"[{tg.ts()}] Claude Code session listing failed: {e!r}", flush=True)
            return []
    if tg._agent_name(cfg) == "cursor":
        try:
            return [{"id": s.id, "title": s.title, "directory": s.directory,
                     "time": {"updated": s.updated}, "agent": s.agent}
                    for s in tg._agent_adapter(cfg).list_sessions()]
        except Exception as e:
            tg.log(f"[{tg.ts()}] Cursor session listing failed: {e!r}", flush=True)
            return []
    try:
        # The session picker is deliberately not restricted to the startup
        # directory; users may select any project visible to their OpenCode API.
        items = tg._session_items(cfg, "")
    except Exception as e:
        tg.log(f"[{tg.ts()}] session listing failed: {e!r}", flush=True)
        return []
    sessions = []
    for session in items:
        if not isinstance(session, dict) or session.get("parentID"):
            continue
        if (session.get("time") or {}).get("archived"):
            continue
        directory = str(session.get("directory") or "")
        sessions.append(session)
    return sessions


def _active_session_id():
    try:
        data = json.loads(tg.ACTIVE_SESSION.read_text(encoding="utf-8"))
        return str(data.get("id") or "")
    except (OSError, ValueError, TypeError):
        return ""


def _set_active_session(session):
    """Persist the selected session atomically; no settings/env edits required."""
    tg.ACTIVE_SESSION.parent.mkdir(parents=True, exist_ok=True)
    tmp = tg.ACTIVE_SESSION.with_suffix(".tmp")
    payload = json.dumps({"id": session.get("id"),
                          "title": session.get("title") or "Untitled",
                          "directory": session.get("directory") or ""},
                         ensure_ascii=False).encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(payload)
    os.replace(tmp, tg.ACTIVE_SESSION)


def discover_session(cfg):
    """Newest non-archived root session (prefers this home directory)."""
    home = urllib.parse.quote(str(pathlib.Path.home()), safe="")
    for query in (f"&directory={home}",):
        try:
            items = tg._session_items(cfg, query)
        except Exception as e:
            tg.log(f"[{tg.ts()}] discovery failed: {e!r}", flush=True)
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
            if best is None or tg._updated(s) > tg._updated(best):
                best = s
        if best:
            return best.get("id") or None
    return None


def _session_by_id(cfg, sid):
    if tg._agent_name(cfg) in ("codex", "claude-code", "claude", "cursor"):
        if tg._agent_name(cfg) == "cursor":
            session = tg._agent_adapter(cfg).validate_session(sid)
            return ({"id": session.id, "title": session.title,
                     "directory": session.directory, "agent": session.agent}
                    if session else None)
        return next((s for s in tg.list_sessions(cfg) if str(s.get("id")) == str(sid)), None)
    if not re.fullmatch(r"ses[0-9A-Za-z_-]{6,80}", str(sid or "")):
        return None
    return next((s for s in tg.list_sessions(cfg) if str(s.get("id")) == sid), None)


def resolve_session(cfg):
    """Resolve the injection target session (auto-discovery by default)."""
    if tg._agent_name(cfg) in ("codex", "claude-code", "claude", "cursor"):
        selected = tg._active_session_id()
        if selected and tg._session_by_id(cfg, selected):
            return selected, "telegram-selected"
        sessions = tg.list_sessions(cfg)
        return (str(sessions[0]["id"]), "discovered") if sessions else ("", "none")
    selected = tg._active_session_id()
    if selected and re.fullmatch(r"ses[0-9A-Za-z_-]{6,80}", selected):
        # Do not route stale or cross-directory selections into another project.
        if tg._session_by_id(cfg, selected):
            return selected, "telegram-selected"
        try:
            if tg._active_session_id() == selected:
                tg.ACTIVE_SESSION.unlink(missing_ok=True)
        except OSError:
            pass
    mode = (cfg.get("OPENCODE_SESSION_MODE") or "auto").strip().lower()
    pin = (cfg.get("OPENCODE_SESSION_ID") or "").strip()
    if mode in ("pin", "pinned") and pin and re.fullmatch(r"ses[0-9A-Za-z_-]{6,80}", pin):
        return pin, "pinned"
    sid = tg.discover_session(cfg)
    if sid and re.fullmatch(r"ses[0-9A-Za-z_-]{6,80}", sid):
        return sid, "discovered"
    return "", "none"


def _try_prompt(cfg, sid, body_text, delivery):
    """One admit attempt into a session. Returns True on success."""
    agent_name = tg._agent_name(cfg)
    if agent_name in ("opencode", "") and not re.fullmatch(r"ses[0-9A-Za-z_-]{6,80}", str(sid)):
        tg.log(f"[{tg.ts()}] prompt rejected invalid session id", flush=True)
        return False
    try:
        adapter = tg._agent_adapter(cfg)
        reply = adapter.send_message(sid, body_text, delivery)
    except Exception as e:
        from adapters.codex import CodexAdapterError
        from adapters.cursor import CursorAdapterError
        if isinstance(e, (CodexAdapterError, CursorAdapterError)):
            tg.send_text(cfg, str(e))
            return True
        tg.log(f"[{tg.ts()}] prompt sid={sid} {delivery}: error {e!r}", flush=True)
        return False
    if adapter.name in ("codex", "claude-code", "cursor") and isinstance(reply, str) and reply:
        tg.send_text(cfg, reply[:6000])
        return True
    return bool(reply)
