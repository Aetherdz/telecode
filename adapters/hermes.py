"""Hermes Agent adapter for Nous Research's Hermes CLI."""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import time

from .base import AgentSession

_SESSION_ID_RE = re.compile(r"^[0-9a-zA-Z_-]{1,128}$")
_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_MARKDOWN_STRIP_RE = re.compile(r"^[#*`_~\s]+|[#*`_~\s]+$")


class HermesAdapterError(RuntimeError):
    """A clear, user-displayable Hermes Agent failure."""


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
    """Clean terminal startup banners, Rich box borders, and escape codes from CLI output."""
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
        is_banner_title = "hermes" in stripped.lower() and (
            "agent" in stripped.lower() or "version" in stripped.lower() or "nous" in stripped.lower()
        )
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


def _hermes_home() -> pathlib.Path:
    config = os.environ.get("HERMES_HOME") or os.environ.get("HERMES_CONFIG_DIR")
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
        """List sessions from ~/.hermes/state.db (SQLite) and ~/.hermes/sessions (JSON/JSONL)."""
        sessions_by_id: dict[str, AgentSession] = {}

        # 1. Check state.db SQLite database if present
        db_path = self.config_dir / "state.db"
        if db_path.is_file():
            try:
                import sqlite3
                uri = f"file:{db_path.resolve()}?mode=ro"
                try:
                    conn = sqlite3.connect(uri, uri=True, timeout=1.0)
                except (sqlite3.OperationalError, sqlite3.DatabaseError):
                    conn = sqlite3.connect(str(db_path), timeout=1.0)
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("PRAGMA table_info(sessions)")
                    cols = {row[1] for row in cursor.fetchall()}
                    if cols and "id" in cols:
                        title_expr = "title" if "title" in cols else ("display_name" if "display_name" in cols else "id")
                        started_expr = "started_at" if "started_at" in cols else "0.0"
                        ended_expr = "ended_at" if "ended_at" in cols else "0.0"
                        ws_expr = "workspace" if "workspace" in cols else "''"
                        query = f"""
                            SELECT id, {title_expr}, {started_expr}, {ended_expr}, {ws_expr}
                            FROM sessions
                            ORDER BY COALESCE(NULLIF({ended_expr}, 0), NULLIF({started_expr}, 0), 0) DESC
                            LIMIT 100
                        """
                        cursor.execute(query)
                        for sid, raw_title, started, ended, ws in cursor.fetchall():
                            sid = str(sid or "")
                            if not _SESSION_ID_RE.match(sid):
                                continue
                            title = _clean_title(raw_title) or sid
                            try:
                                up = float(ended) if ended else (float(started) if started else 0.0)
                            except (ValueError, TypeError):
                                up = 0.0
                            ws_dir = str(ws or self.workspace)
                            sessions_by_id[sid] = AgentSession(sid, title, ws_dir, self.name, updated=up)
            except (sqlite3.Error, OSError):
                pass

        # 2. Check ~/.hermes/sessions JSON and JSONL files
        root = self.config_dir / "sessions"
        if root.is_dir():
            try:
                for path in sorted(root.glob("*.json*"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
                    if path.is_symlink():
                        continue
                    sid = path.stem
                    if not _SESSION_ID_RE.match(sid) or sid in sessions_by_id:
                        continue
                    title = ""
                    updated = path.stat().st_mtime
                    try:
                        if path.suffix == ".json":
                            data = json.loads(path.read_text(encoding="utf-8"))
                            if isinstance(data, dict):
                                title = _clean_title(data.get("title") or data.get("name") or sid)
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
                                        title = _clean_title(rec.get("title") or rec.get("summary") or "")
                                        if "timestamp" in rec:
                                            try:
                                                updated = float(rec["timestamp"])
                                            except (ValueError, TypeError):
                                                pass
                    except (OSError, ValueError):
                        continue
                    sessions_by_id[sid] = AgentSession(
                        sid, title or sid, str(self.workspace), self.name, updated=updated
                    )
            except OSError:
                pass

        sessions = list(sessions_by_id.values())
        sessions.sort(key=lambda s: s.updated, reverse=True)
        return sessions[:100]

    def validate_session(self, session_id: str) -> AgentSession | None:
        """Fast and reliable lookup for a Hermes session."""
        sid = str(session_id or "").strip()
        if not _SESSION_ID_RE.match(sid):
            return None

        # 1. Fast path: check exact session JSON file
        json_path = self.config_dir / "sessions" / f"{sid}.json"
        if json_path.is_file():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    title = _clean_title(data.get("title") or data.get("name") or sid)
                    up = json_path.stat().st_mtime
                    if "updated_at" in data:
                        try:
                            up = float(data["updated_at"])
                        except (ValueError, TypeError):
                            pass
                    ws = str(data.get("workspace") or self.workspace)
                    return AgentSession(sid, title or sid, ws, self.name, updated=up)
            except (OSError, ValueError):
                pass

        # 2. Fast path: check exact session JSONL file
        jsonl_path = self.config_dir / "sessions" / f"{sid}.jsonl"
        if jsonl_path.is_file():
            try:
                with jsonl_path.open("r", encoding="utf-8", errors="replace") as f:
                    first_line = f.readline()
                    title = ""
                    up = jsonl_path.stat().st_mtime
                    if first_line:
                        rec = json.loads(first_line)
                        if isinstance(rec, dict):
                            title = _clean_title(rec.get("title") or rec.get("summary") or "")
                            if "timestamp" in rec:
                                try:
                                    up = float(rec["timestamp"])
                                except (ValueError, TypeError):
                                    pass
                    return AgentSession(sid, title or sid, str(self.workspace), self.name, updated=up)
            except (OSError, ValueError):
                pass

        # 3. Fast path: check state.db SQLite database
        db_path = self.config_dir / "state.db"
        if db_path.is_file():
            try:
                import sqlite3
                uri = f"file:{db_path.resolve()}?mode=ro"
                try:
                    conn = sqlite3.connect(uri, uri=True, timeout=1.0)
                except (sqlite3.OperationalError, sqlite3.DatabaseError):
                    conn = sqlite3.connect(str(db_path), timeout=1.0)
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("PRAGMA table_info(sessions)")
                    cols = {row[1] for row in cursor.fetchall()}
                    if cols and "id" in cols:
                        title_expr = "title" if "title" in cols else ("display_name" if "display_name" in cols else "id")
                        started_expr = "started_at" if "started_at" in cols else "0.0"
                        ended_expr = "ended_at" if "ended_at" in cols else "0.0"
                        ws_expr = "workspace" if "workspace" in cols else "''"
                        cursor.execute(
                            f"SELECT id, {title_expr}, {started_expr}, {ended_expr}, {ws_expr} FROM sessions WHERE id = ? LIMIT 1",
                            (sid,),
                        )
                        row = cursor.fetchone()
                        if row:
                            _, raw_title, started, ended, ws = row
                            title = _clean_title(raw_title) or sid
                            try:
                                up = float(ended) if ended else (float(started) if started else 0.0)
                            except (ValueError, TypeError):
                                up = 0.0
                            ws_dir = str(ws or self.workspace)
                            return AgentSession(sid, title, ws_dir, self.name, updated=up)
            except (sqlite3.Error, OSError):
                pass

        # 4. Fallback to list_sessions scan
        return next((s for s in self.list_sessions() if s.id == sid), None)

    def create_session(self, title: str) -> AgentSession:
        """Create a new Hermes session entry matching Hermes expectations."""
        import uuid
        clean = _clean_title(title)
        title = clean if clean else "Untitled"
        sid = f"hermes-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        root = self.config_dir / "sessions"
        now = time.time()
        try:
            root.mkdir(parents=True, exist_ok=True)
            session_file = root / f"{sid}.json"
            data = {
                "id": sid,
                "title": title,
                "created_at": now,
                "updated_at": now,
                "workspace": str(self.workspace),
            }
            session_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as e:
            raise HermesAdapterError(f"Could not create Hermes session: {e!r}") from e

        # Also register in state.db if database exists
        db_path = self.config_dir / "state.db"
        if db_path.is_file():
            try:
                import sqlite3
                with sqlite3.connect(str(db_path), timeout=2.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute("PRAGMA table_info(sessions)")
                    cols = {row[1] for row in cursor.fetchall()}
                    if cols and "id" in cols:
                        fields = ["id", "source"]
                        vals: list[str | float] = [sid, "telecode"]
                        if "title" in cols:
                            fields.append("title")
                            vals.append(title)
                        if "started_at" in cols:
                            fields.append("started_at")
                            vals.append(now)
                        if "ended_at" in cols:
                            fields.append("ended_at")
                            vals.append(now)
                        if "workspace" in cols:
                            fields.append("workspace")
                            vals.append(str(self.workspace))
                        placeholders = ", ".join(["?"] * len(fields))
                        col_names = ", ".join(fields)
                        cursor.execute(
                            f"INSERT OR REPLACE INTO sessions ({col_names}) VALUES ({placeholders})",
                            vals,
                        )
            except (sqlite3.Error, OSError):
                pass

        return AgentSession(sid, title, str(self.workspace), self.name, updated=now)

    def send_message(self, session_id: str, text: str, delivery: str = "queue") -> str | None:
        """Run verified Hermes command to resume session and send prompt."""
        sid = str(session_id or "").strip()
        if not _SESSION_ID_RE.match(sid):
            return None

        # Verify Hermes CLI binary availability
        binary_found = shutil.which(self.binary) or (os.path.isabs(self.binary) and os.path.isfile(self.binary))
        if not binary_found:
            raise HermesAdapterError(
                f"Hermes CLI '{self.binary}' is not installed or not found in PATH. "
                "Install Hermes Agent with: pip install hermes-agent or pipx install hermes-agent "
                "(see https://github.com/NousResearch/hermes-agent)"
            )

        # Verified non-interactive Hermes command: hermes chat --resume <session_id> -q <text>
        cmd = [self.binary, "chat", "--resume", sid, "-q", text]

        env = dict(os.environ)
        env["NO_COLOR"] = "1"
        env["TERM"] = "dumb"
        if self.config_dir:
            env["HERMES_HOME"] = str(self.config_dir)

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
            raise HermesAdapterError(
                f"Hermes CLI '{self.binary}' is not installed or not found in PATH. "
                "Install Hermes Agent with: pip install hermes-agent or pipx install hermes-agent "
                "(see https://github.com/NousResearch/hermes-agent)"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise HermesAdapterError(f"hermes execution timed out after {self.timeout}s: {e!r}") from e
        except OSError as e:
            raise HermesAdapterError(f"hermes execution failed: {e!r}") from e

        if result.returncode:
            err = (result.stderr or result.stdout or "hermes execution failed").strip()
            err = _ANSI_ESCAPE_RE.sub("", err).strip()
            raise HermesAdapterError(err[:200])

        output = result.stdout or ""
        return _strip_banner(output)
