"""Cursor CLI adapter for resuming a known Cursor Agent thread."""
import itertools
import html
import json
import os
import pathlib
import re
import stat
import subprocess

from .base import AgentSession

_SESSION_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class CursorAdapterError(RuntimeError):
    """A clear, user-displayable Cursor CLI failure."""


class CursorAdapter:
    name = "cursor"

    def __init__(self, binary="agent", workspace=None, timeout=600, config_dir=None, model=None):
        self.binary = binary
        self.workspace = pathlib.Path(
            workspace or os.environ.get("CURSOR_WORKSPACE") or pathlib.Path.home()
        ).expanduser().resolve()
        self.config_dir = pathlib.Path(
            config_dir or os.environ.get("CURSOR_CONFIG_DIR") or pathlib.Path.home() / ".cursor"
        ).expanduser()
        self.timeout = timeout
        self.model = str(model or "").strip()

    def list_sessions(self):
        """Best-effort read-only listing from Cursor's local chat metadata."""
        root = self.config_dir / "chats"
        if not root.is_dir():
            return []
        sessions = []
        try:
            paths = root.glob("*/*/meta.json")
            for path in itertools.islice(paths, 2000):
                try:
                    if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():
                        continue
                    info = path.stat()
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024:
                        continue
                    sid = path.parent.name
                    if not _SESSION_ID_RE.fullmatch(sid):
                        continue
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        continue
                    cwd = str(data.get("cwd") or "")
                    if not cwd:
                        continue
                    cwd = str(pathlib.Path(cwd).expanduser().resolve())
                    if not pathlib.Path(cwd).is_dir():
                        continue
                    updated_ms = data.get("updatedAtMs") or data.get("createdAtMs") or 0
                    try:
                        updated = float(updated_ms) / 1000
                    except (TypeError, ValueError, OverflowError):
                        updated = info.st_mtime
                    title = data.get("title")
                    if not isinstance(title, str) or not title.strip():
                        title = self._transcript_title(sid) or "Untitled Cursor chat"
                    sessions.append(AgentSession(sid, title.strip()[:80], cwd,
                                                 self.name, updated=updated))
                except (OSError, UnicodeError, ValueError, TypeError):
                    continue
        except OSError:
            return []
        sessions.sort(key=lambda session: session.updated, reverse=True)
        return sessions[:100]

    def _transcript_title(self, session_id):
        """Use a short first-user-message excerpt when Cursor metadata has no title."""
        root = self.config_dir / "projects"
        if not root.is_dir():
            return ""
        try:
            paths = itertools.islice(
                root.glob(f"*/agent-transcripts/{session_id}/{session_id}.jsonl"), 20
            )
            for path in paths:
                try:
                    if path.is_symlink() or path.parent.is_symlink():
                        continue
                    with path.open("r", encoding="utf-8", errors="replace") as stream:
                        for _ in range(8):
                            line = stream.readline(64 * 1024)
                            if not line:
                                break
                            row = json.loads(line)
                            if row.get("role") != "user":
                                continue
                            content = (row.get("message") or {}).get("content") or []
                            text = " ".join(
                                str(item.get("text") or "") for item in content
                                if isinstance(item, dict) and item.get("type") == "text"
                            )
                            match = re.search(r"<user_query>\s*(.*?)\s*</user_query>",
                                              text, flags=re.DOTALL)
                            if match:
                                text = match.group(1)
                            text = html.unescape(re.sub(r"<[^>]*>", " ", text))
                            text = " ".join(text.split())
                            if len(text) >= 4:
                                return text[:72].rstrip()
                            continue
                except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
                    continue
        except OSError:
            return ""
        return ""

    def create_session(self, title):
        """Create an empty Cursor chat in the configured workspace and return its ID."""
        title = " ".join(str(title or "").split())
        if not title:
            raise CursorAdapterError("Session name is required.")
        if len(title) > 80:
            raise CursorAdapterError("Session name must be 80 characters or fewer.")
        if not self.workspace.is_dir():
            raise CursorAdapterError(
                "Cursor workspace is unavailable. Set CURSOR_WORKSPACE to an existing project directory."
            )
        try:
            result = subprocess.run(
                [self.binary, "create-chat"], cwd=str(self.workspace),
                capture_output=True, text=True, timeout=60, check=False,
            )
        except FileNotFoundError as exc:
            raise CursorAdapterError(
                "Cursor Agent CLI was not found. Install it or set CURSOR_AGENT_BIN."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise CursorAdapterError("Cursor could not create a chat before the 60-second timeout.") from exc
        except OSError as exc:
            raise CursorAdapterError(f"Could not start Cursor Agent: {exc}") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout or "Cursor could not create a chat.")
            raise CursorAdapterError(f"Cursor chat creation failed: {detail.strip().replace(chr(10), ' ')[:500]}")
        sid = (result.stdout or "").strip()
        if not _SESSION_ID_RE.fullmatch(sid):
            raise CursorAdapterError("Cursor did not return a valid session ID when creating the chat.")
        # Cursor's create-chat command does not accept a title. Keep the requested
        # label in TeleCode's active-session state; Cursor can title the chat later.
        return AgentSession(sid, title, str(self.workspace), self.name)

    def validate_session(self, session_id):
        sid = str(session_id or "")
        if not _SESSION_ID_RE.fullmatch(sid):
            return None
        return AgentSession(sid, "Cursor session", str(self.workspace), self.name)

    def build_argv(self, session_id, text):
        if self.validate_session(session_id) is None:
            raise CursorAdapterError("Invalid Cursor session ID.")
        args = [self.binary, "--resume", session_id, "--print", "--output-format", "text"]
        if self.model:
            args += ["--model", self.model]
        return args + [str(text)]

    def send_message(self, session_id, text, delivery="queue"):
        session = self.validate_session(session_id)
        if session is None:
            raise CursorAdapterError("Invalid Cursor session ID.")
        listed = next((item for item in self.list_sessions() if item.id == session_id), None)
        workspace = pathlib.Path(listed.directory) if listed else self.workspace
        if not workspace.is_dir():
            raise CursorAdapterError(
                "Cursor workspace is unavailable. Set CURSOR_WORKSPACE to an existing project directory."
            )
        try:
            result = subprocess.run(
                self.build_argv(session_id, text), cwd=str(workspace),
                capture_output=True, text=True, timeout=self.timeout, check=False,
            )
        except FileNotFoundError as exc:
            raise CursorAdapterError(
                "Cursor Agent CLI was not found. Install it or set CURSOR_AGENT_BIN."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise CursorAdapterError("Cursor Agent did not finish before the 10-minute timeout.") from exc
        except OSError as exc:
            raise CursorAdapterError(f"Could not start Cursor Agent: {exc}") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout or "Cursor Agent exited with an error.")
            detail = detail.strip().replace("\n", " ")[:500]
            raise CursorAdapterError(f"Cursor Agent failed: {detail}")
        return (result.stdout or "").strip()
