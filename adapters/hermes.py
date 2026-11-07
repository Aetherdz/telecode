"""Hermes Agent adapter for Nous Research's Hermes CLI."""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import time

from .base import AgentSession

_SESSION_ID_RE = re.compile(r"^[0-9a-zA-Z_-]{1,128}$")


class HermesAdapterError(RuntimeError):
    """A clear, user-displayable Hermes Agent failure."""


def _hermes_home() -> pathlib.Path:
    config = os.environ.get("HERMES_CONFIG_DIR")
    if config:
        return pathlib.Path(config).expanduser()
    return pathlib.Path.home() / ".hermes"


class HermesAdapter:
    name = "hermes"

    def __init__(
        self,
        binary: str = "hermes",
        timeout: int = 600,
        config_dir: pathlib.Path | None = None,
        workspace: pathlib.Path | None = None,
    ):
        self.binary = binary
        self.timeout = timeout
        self.config_dir = pathlib.Path(config_dir).expanduser() if config_dir else _hermes_home()
        self.workspace = pathlib.Path(
            workspace or os.environ.get("HERMES_WORKSPACE") or pathlib.Path.home()
        ).expanduser().resolve()

    def list_sessions(self) -> list[AgentSession]:
        """List sessions from ~/.hermes/sessions or metadata if present."""
        root = self.config_dir / "sessions"
        if not root.is_dir():
            return []
        sessions: list[AgentSession] = []
        try:
            for path in sorted(root.glob("*.json*"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
                if path.is_symlink():
                    continue
                sid = path.stem
                if not _SESSION_ID_RE.match(sid):
                    continue
                title = ""
                updated = path.stat().st_mtime
                try:
                    if path.suffix == ".json":
                        data = json.loads(path.read_text(encoding="utf-8"))
                        if isinstance(data, dict):
                            title = str(data.get("title") or data.get("name") or sid)[:80]
                            if "updated_at" in data:
                                try:
                                    updated = float(data["updated_at"])
                                except (ValueError, TypeError):
                                    pass
                    elif path.suffix == ".jsonl":
                        with path.open("r", encoding="utf-8", errors="replace") as f:
                            first_line = f.readline()
                            if first_line:
                                rec = json.loads(first_line)
                                if isinstance(rec, dict):
                                    title = str(rec.get("title") or rec.get("summary") or "")[:80]
                except (OSError, ValueError):
                    continue
                sessions.append(AgentSession(sid, title or sid, str(self.workspace), self.name, updated=updated))
        except OSError:
            return []
        sessions.sort(key=lambda s: s.updated, reverse=True)
        return sessions[:100]

    def validate_session(self, session_id: str) -> AgentSession | None:
        return next((s for s in self.list_sessions() if s.id == session_id), None)

    def send_message(self, session_id: str, text: str, delivery: str = "queue") -> str | None:
        if not _SESSION_ID_RE.match(str(session_id or "")):
            return None
        cmd = [self.binary, "chat", "--resume", str(session_id), "--message", text]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise HermesAdapterError(f"hermes execution failed: {e!r}") from e
        if result.returncode:
            raise HermesAdapterError((result.stderr or "hermes execution failed").strip()[:180])
        return (result.stdout or "").strip()
