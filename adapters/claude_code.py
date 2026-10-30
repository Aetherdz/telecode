"""Claude Code adapter: routes prompts through `claude --resume <session-id>`.

Claude Code keeps durable session transcripts locally, so a Telegram message can
be delivered to an existing session by resuming it headlessly. Listing parses
~/.claude/projects/*/*.jsonl transcripts, whose session files are named by
session id and carry summaries and timestamps.
"""
import json
import os
import pathlib
import re
import subprocess
import time

from .base import AgentSession

_SESSION_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def _projects_root():
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    if config:
        return pathlib.Path(config).expanduser() / "projects"
    return pathlib.Path.home() / ".claude" / "projects"


class ClaudeCodeAdapter:
    name = "claude-code"

    def __init__(self, binary="claude", timeout=600):
        self.binary = binary
        self.timeout = timeout

    def list_sessions(self):
        root = _projects_root()
        if not root.is_dir():
            return []
        sessions = []
        for project_dir in root.iterdir():
            if not project_dir.is_dir():
                continue
            for path in sorted(project_dir.glob("*.jsonl"),
                               key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
                sid = path.stem
                if not _SESSION_ID_RE.match(sid):
                    continue
                title, updated = "", path.stat().st_mtime
                try:
                    with path.open("r", encoding="utf-8", errors="replace") as f:
                        for line in f:
                            try:
                                rec = json.loads(line)
                            except ValueError:
                                continue
                            if rec.get("type") == "summary" and rec.get("summary"):
                                title = str(rec["summary"])[:80]
                                break
                            if not title and rec.get("type") == "user" and isinstance(rec.get("message"), dict):
                                content = rec["message"].get("content")
                                if isinstance(content, str) and content.strip():
                                    title = content.strip().replace("\n", " ")[:80]
                            stamp = rec.get("timestamp")
                            if isinstance(stamp, str):
                                try:
                                    updated = max(updated, time.mktime(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")))
                                except ValueError:
                                    pass
                except OSError:
                    continue
                sessions.append(AgentSession(sid, title or "Untitled", str(project_dir), self.name,
                                             updated=updated))
        sessions.sort(key=lambda s: s.updated, reverse=True)
        return sessions[:100]

    def validate_session(self, session_id):
        return next((s for s in self.list_sessions() if s.id == session_id), None)

    def send_message(self, session_id, text, delivery="queue"):
        """Resume the session headlessly; returns the agent reply text, or None."""
        if not _SESSION_ID_RE.match(str(session_id or "")):
            return None
        cmd = [self.binary, "--resume", session_id, "--print", "--output-format", "text"]
        try:
            result = subprocess.run(cmd, input=text, capture_output=True,
                                    text=True, timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(f"claude resume failed: {e!r}") from e
        if result.returncode:
            raise RuntimeError((result.stderr or "claude resume failed").strip()[:180])
        return (result.stdout or "").strip()
