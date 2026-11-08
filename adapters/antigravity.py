"""Google Antigravity CLI (agy) adapter."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import time
import uuid

from .base import AgentSession

_SESSION_ID_RE = re.compile(r"^[0-9a-zA-Z_-]{1,128}$")
_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_MARKDOWN_STRIP_RE = re.compile(r"^[#*`_~\s]+|[#*`_~\s]+$")

DEFAULT_ANTIGRAVITY_MODELS = [
    {"id": "gemini-4-argon-medium", "providerID": "Google Gemini", "name": "Gemini 4 Argon (Medium)"},
    {"id": "gemini-4-argon-high", "providerID": "Google Gemini", "name": "Gemini 4 Argon (High)"},
    {"id": "gemini-4-argon-low", "providerID": "Google Gemini", "name": "Gemini 4 Argon (Low)"},
    {"id": "gemini-3.8-flash-high", "providerID": "Google Gemini", "name": "Gemini 3.8 Flash (High)"},
    {"id": "gemini-3.8-flash-medium", "providerID": "Google Gemini", "name": "Gemini 3.8 Flash (Medium)"},
    {"id": "gemini-3.8-flash-low", "providerID": "Google Gemini", "name": "Gemini 3.8 Flash (Low)"},
    {"id": "claude-opus-5-5-medium", "providerID": "Anthropic Claude", "name": "Claude Opus 5.5 (Medium)"},
    {"id": "claude-opus-5-5-high", "providerID": "Anthropic Claude", "name": "Claude Opus 5.5 (High)"},
    {"id": "claude-opus-5-5-low", "providerID": "Anthropic Claude", "name": "Claude Opus 5.5 (Low)"},
    {"id": "claude-sonnet-5-5-medium", "providerID": "Anthropic Claude", "name": "Claude Sonnet 5.5 (Medium)"},
    {"id": "claude-sonnet-5-5-high", "providerID": "Anthropic Claude", "name": "Claude Sonnet 5.5 (High)"},
    {"id": "claude-sonnet-5-5-low", "providerID": "Anthropic Claude", "name": "Claude Sonnet 5.5 (Low)"},
    {"id": "gpt-oss-120b-medium", "providerID": "OpenAI / OSS", "name": "GPT-OSS 120B (Medium)"},
]


class AntigravityAdapterError(RuntimeError):
    """A clear, user-displayable Antigravity failure."""


def _clean_title(text: str) -> str:
    """Strip ANSI escape sequences, markdown decorators, and collapse whitespace."""
    if not text:
        return ""
    clean = _ANSI_ESCAPE_RE.sub("", str(text))
    clean = " ".join(clean.split())
    clean = _MARKDOWN_STRIP_RE.sub("", clean).strip()
    clean = clean.replace("`", "").replace("**", "").replace("__", "")
    return clean[:80]


def _strip_banner(text: str) -> str:
    """Clean terminal startup banners and escape codes from CLI output."""
    if not text:
        return ""
    clean = _ANSI_ESCAPE_RE.sub("", text)
    clean = clean.replace("\r\n", "\n").replace("\r", "\n")
    lines = clean.split("\n")

    start_idx = 0
    in_banner = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if in_banner:
                continue
            start_idx = i + 1
            continue
        is_box_border = bool(re.match(r"^[╭╮╰╯─│┌┐└┘═║\s─\-_=*+]{3,}$", stripped))
        is_banner_title = "antigravity" in stripped.lower() or "agy" in stripped.lower()
        is_box_line = bool(re.match(r"^[│║|].*[│║|]$", stripped))
        if is_box_border or is_banner_title or (in_banner and is_box_line):
            in_banner = True
            start_idx = i + 1
            if any(ch in stripped for ch in "╰╯└┘"):
                in_banner = False
        else:
            break

    result = "\n".join(lines[start_idx:]).strip()
    return result if result else clean.strip()


def _parse_time(val: any) -> float:
    """Parse timestamp from float, int, or ISO 8601 string to epoch seconds."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    text = str(val).strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        pass
    # Try parsing ISO timestamp (e.g. 2026-11-07 11:19:26.073408996+00:00)
    try:
        # Strip nanosecond precision if present (> 6 fraction digits)
        clean_text = re.sub(r"(\.\d{6})\d+", r"\1", text)
        dt = datetime.fromisoformat(clean_text)
        return dt.timestamp()
    except (ValueError, TypeError, AttributeError):
        return 0.0


def _parse_workspace(ws_val: any, fallback: pathlib.Path) -> str:
    """Parse workspace directory from JSON array, string URI, or path."""
    if not ws_val:
        return str(fallback)
    if isinstance(ws_val, list) and ws_val:
        first = str(ws_val[0])
        return first.replace("file://", "")
    text = str(ws_val).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list) and parsed:
                return str(parsed[0]).replace("file://", "")
        except (ValueError, TypeError):
            pass
    if text.startswith("file://"):
        return text.replace("file://", "")
    return text or str(fallback)


def _antigravity_home() -> pathlib.Path:
    config = os.environ.get("ANTIGRAVITY_HOME") or os.environ.get("AGY_HOME")
    if config:
        return pathlib.Path(config).expanduser()
    primary = pathlib.Path.home() / ".gemini/antigravity-cli"
    if primary.is_dir():
        return primary
    alt = pathlib.Path.home() / ".gemini/antigravity"
    if alt.is_dir():
        return alt
    return primary


class AntigravityAdapter:
    name = "antigravity"

    def __init__(
        self,
        binary: str = "agy",
        timeout: int = 600,
        config_dir: pathlib.Path | None = None,
        workspace: pathlib.Path | None = None,
        model: str | None = None,
    ):
        self.binary = binary
        self.timeout = timeout
        self.config_dir = pathlib.Path(config_dir).expanduser() if config_dir else _antigravity_home()
        self.workspace = pathlib.Path(
            workspace or os.environ.get("ANTIGRAVITY_WORKSPACE") or pathlib.Path.home()
        ).expanduser().resolve()
        self.model = str(model or "").strip()

    def list_models(self) -> list[dict]:
        """Query available models from 'agy models' or return verified catalog."""
        bin_path = self._resolve_binary()
        if bin_path:
            try:
                env = dict(os.environ)
                env["NO_COLOR"] = "1"
                env["TERM"] = "dumb"
                res = subprocess.run([bin_path, "models"], capture_output=True, text=True, timeout=15, check=False, env=env)
                if res.returncode == 0 and res.stdout:
                    models = []
                    for line in res.stdout.splitlines():
                        clean = _ANSI_ESCAPE_RE.sub("", line).strip()
                        if not clean or "fetching" in clean.lower():
                            continue
                        parts = clean.split(None, 1)
                        if parts:
                            mid = parts[0].strip()
                            name = parts[1].strip() if len(parts) > 1 else mid
                            if mid.startswith("gemini-"):
                                provider = "Google Gemini"
                            elif mid.startswith("claude-"):
                                provider = "Anthropic Claude"
                            elif mid.startswith("gpt-"):
                                provider = "OpenAI / OSS"
                            else:
                                provider = "Google Antigravity"
                            models.append({"id": mid, "providerID": provider, "name": name})
                    if models:
                        return models
            except (subprocess.SubprocessError, OSError):
                pass
        return list(DEFAULT_ANTIGRAVITY_MODELS)

    def _resolve_binary(self) -> str | None:
        """Find the agy/antigravity binary executable."""
        candidates = [
            self.binary,
            "agy",
            "antigravity",
            str(pathlib.Path.home() / ".local/bin/agy"),
            str(pathlib.Path.home() / ".gemini/bin/agy"),
            str(pathlib.Path.home() / ".local/bin/antigravity"),
        ]
        for c in candidates:
            if not c:
                continue
            which = shutil.which(c)
            if which:
                return which
            if os.path.isabs(c) and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    def list_sessions(self) -> list[AgentSession]:
        """List sessions from conversation_summaries.db (SQLite) or conversations directory."""
        sessions_by_id: dict[str, AgentSession] = {}

        # 1. Check conversation_summaries.db
        db_path = self.config_dir / "conversation_summaries.db"
        if db_path.is_file():
            try:
                uri = f"file:{db_path.resolve()}?mode=ro"
                try:
                    conn = sqlite3.connect(uri, uri=True, timeout=1.0)
                except (sqlite3.OperationalError, sqlite3.DatabaseError):
                    conn = sqlite3.connect(str(db_path), timeout=1.0)
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("PRAGMA table_info(conversation_summaries)")
                    cols = {row[1] for row in cursor.fetchall()}
                    if cols and "conversation_id" in cols:
                        killed_clause = "WHERE killed = 0" if "killed" in cols else ""
                        query = f"""
                            SELECT conversation_id, title, last_modified_time, workspace_uris
                            FROM conversation_summaries
                            {killed_clause}
                            ORDER BY last_modified_time DESC
                            LIMIT 100
                        """
                        cursor.execute(query)
                        for sid, raw_title, mtime, ws in cursor.fetchall():
                            sid = str(sid or "")
                            if not _SESSION_ID_RE.match(sid):
                                continue
                            title = _clean_title(raw_title) or sid
                            updated = _parse_time(mtime)
                            ws_dir = _parse_workspace(ws, self.workspace)
                            sessions_by_id[sid] = AgentSession(sid, title, ws_dir, self.name, updated=updated)
            except (sqlite3.Error, OSError):
                pass

        # 2. Check conversations directory (<session_id>.db files)
        convs_dir = self.config_dir / "conversations"
        if convs_dir.is_dir():
            try:
                for path in sorted(convs_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
                    sid = path.stem
                    if not _SESSION_ID_RE.match(sid) or sid in sessions_by_id:
                        continue
                    mtime = path.stat().st_mtime
                    sessions_by_id[sid] = AgentSession(sid, sid, str(self.workspace), self.name, updated=mtime)
            except OSError:
                pass

        sessions = list(sessions_by_id.values())
        sessions.sort(key=lambda s: s.updated, reverse=True)
        return sessions[:100]

    def validate_session(self, session_id: str) -> AgentSession | None:
        """Fast lookup for an Antigravity conversation/session."""
        sid = str(session_id or "").strip()
        if not _SESSION_ID_RE.match(sid):
            return None

        # 1. Fast path: check conversation_summaries.db
        db_path = self.config_dir / "conversation_summaries.db"
        if db_path.is_file():
            try:
                uri = f"file:{db_path.resolve()}?mode=ro"
                try:
                    conn = sqlite3.connect(uri, uri=True, timeout=1.0)
                except (sqlite3.OperationalError, sqlite3.DatabaseError):
                    conn = sqlite3.connect(str(db_path), timeout=1.0)
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("PRAGMA table_info(conversation_summaries)")
                    cols = {row[1] for row in cursor.fetchall()}
                    if cols and "conversation_id" in cols:
                        cursor.execute(
                            "SELECT conversation_id, title, last_modified_time, workspace_uris "
                            "FROM conversation_summaries WHERE conversation_id = ? LIMIT 1",
                            (sid,),
                        )
                        row = cursor.fetchone()
                        if row:
                            _, raw_title, mtime, ws = row
                            title = _clean_title(raw_title) or sid
                            updated = _parse_time(mtime)
                            ws_dir = _parse_workspace(ws, self.workspace)
                            return AgentSession(sid, title, ws_dir, self.name, updated=updated)
            except (sqlite3.Error, OSError):
                pass

        # 2. Check direct conversation database file
        conv_file = self.config_dir / "conversations" / f"{sid}.db"
        if conv_file.is_file():
            return AgentSession(sid, sid, str(self.workspace), self.name, updated=conv_file.stat().st_mtime)

        # 3. Check brain directory
        brain_dir = self.config_dir / "brain" / sid
        if brain_dir.is_dir():
            return AgentSession(sid, sid, str(self.workspace), self.name, updated=brain_dir.stat().st_mtime)

        # 4. Fallback scan
        return next((s for s in self.list_sessions() if s.id == sid), None)

    def create_session(self, title: str) -> AgentSession:
        """Create a new Antigravity session entry."""
        clean = _clean_title(title)
        title = clean if clean else "Untitled"
        sid = str(uuid.uuid4())
        now = time.time()
        iso_now = datetime.now(timezone.utc).isoformat()
        ws_uri = json.dumps([f"file://{self.workspace}"])

        db_path = self.config_dir / "conversation_summaries.db"
        if db_path.is_file():
            try:
                with sqlite3.connect(str(db_path), timeout=2.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute("PRAGMA table_info(conversation_summaries)")
                    cols = {row[1] for row in cursor.fetchall()}
                    if cols and "conversation_id" in cols:
                        fields = ["conversation_id", "title", "last_modified_time", "workspace_uris"]
                        vals: list[any] = [sid, title, iso_now, ws_uri]
                        if "last_user_input_time" in cols:
                            fields.append("last_user_input_time")
                            vals.append(iso_now)
                        placeholders = ", ".join(["?"] * len(fields))
                        col_names = ", ".join(fields)
                        cursor.execute(
                            f"INSERT OR REPLACE INTO conversation_summaries ({col_names}) VALUES ({placeholders})",
                            vals,
                        )
            except (sqlite3.Error, OSError):
                pass

        return AgentSession(sid, title, str(self.workspace), self.name, updated=now)

    def send_message(self, session_id: str, text: str, delivery: str = "queue") -> str | None:
        """Resume conversation and execute prompt via Antigravity CLI (agy)."""
        sid = str(session_id or "").strip()
        if not _SESSION_ID_RE.match(sid):
            return None

        bin_path = self._resolve_binary()
        if not bin_path:
            raise AntigravityAdapterError(
                f"Antigravity CLI '{self.binary}' was not found in PATH or ~/.local/bin/agy. "
                "Ensure Google Antigravity CLI is installed."
            )

        # agy --conversation <sid> --dangerously-skip-permissions [--model <model>] --print <text>
        cmd = [bin_path, "--conversation", sid, "--dangerously-skip-permissions"]
        if self.model:
            cmd += ["--model", self.model]
        cmd += ["--print", text]

        env = dict(os.environ)
        env["NO_COLOR"] = "1"
        env["TERM"] = "dumb"

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                env=env,
                cwd=str(self.workspace) if self.workspace.is_dir() else None,
            )
        except FileNotFoundError as e:
            raise AntigravityAdapterError(
                f"Antigravity CLI '{self.binary}' is not installed or not found in PATH."
            ) from e
        except subprocess.TimeoutExpired as e:
            raise AntigravityAdapterError(f"Antigravity execution timed out after {self.timeout}s: {e!r}") from e
        except OSError as e:
            raise AntigravityAdapterError(f"Antigravity execution failed: {e!r}") from e

        if result.returncode:
            err = (result.stderr or result.stdout or "Antigravity execution failed").strip()
            err = _ANSI_ESCAPE_RE.sub("", err).strip()
            raise AntigravityAdapterError(err[:200])

        output = result.stdout or ""
        return _strip_banner(output)
