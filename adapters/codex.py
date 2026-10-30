"""Experimental inbound adapter for resuming Codex CLI sessions."""
import json
import itertools
import os
import pathlib
import re
import signal
import subprocess
import threading

from .base import AgentSession

_SESSION_ID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_MAX_ROLLOUT_BYTES = 8 * 1024 * 1024
_MAX_OUTPUT_CHARS = 32 * 1024


class CodexAdapterError(RuntimeError):
    """A clear, user-displayable Codex adapter failure."""


def _read_bounded(stream, chunks):
    collected = bytearray()
    while True:
        try:
            chunk = stream.read(8192)
        except (OSError, ValueError):
            break
        if not chunk:
            break
        remaining = _MAX_OUTPUT_CHARS - len(collected)
        if remaining > 0:
            collected.extend(chunk[:remaining])
    chunks.append(collected.decode("utf-8", errors="replace"))


def _kill_process_tree(process):
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                           capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _codex_home():
    return pathlib.Path(os.environ.get("CODEX_HOME") or pathlib.Path.home() / ".codex").expanduser()


class CodexAdapter:
    name = "codex"

    def __init__(self, binary="codex", timeout=600, sessions_root=None, workspace_write=None):
        self.binary = binary
        self.timeout = timeout
        self.sessions_root = pathlib.Path(sessions_root) if sessions_root else _codex_home() / "sessions"
        self.workspace_write = workspace_write

    def list_sessions(self):
        if not self.sessions_root.is_dir():
            return []
        found = {}
        try:
            paths = itertools.islice(self.sessions_root.rglob("rollout-*.jsonl"), 5000)
            for path in paths:
                try:
                    if path.stat().st_size > _MAX_ROLLOUT_BYTES:
                        continue
                    with path.open(encoding="utf-8") as stream:
                        first = stream.readline(1024 * 1024)
                    record = json.loads(first)
                    payload = record.get("payload", {}) if isinstance(record, dict) else {}
                    sid = str(payload.get("id") or "") if record.get("type") == "session_meta" and isinstance(payload, dict) else ""
                    cwd = str(payload.get("cwd") or "") if isinstance(payload, dict) else ""
                    if not _SESSION_ID_RE.fullmatch(sid) or not cwd:
                        continue
                    stat = path.stat()
                    session = AgentSession(sid, pathlib.Path(cwd).name or cwd, cwd, self.name, stat.st_mtime)
                    if sid not in found or found[sid].updated < session.updated:
                        found[sid] = session
                except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
                    continue
        except OSError as exc:
            raise CodexAdapterError(f"Could not read Codex sessions: {exc}") from exc
        return sorted(found.values(), key=lambda session: session.updated, reverse=True)[:100]

    def validate_session(self, session_id):
        if not _SESSION_ID_RE.fullmatch(str(session_id or "")):
            return None
        return next((session for session in self.list_sessions() if session.id == session_id), None)

    def build_argv(self, session_id, text):
        if not _SESSION_ID_RE.fullmatch(str(session_id or "")):
            raise CodexAdapterError("Invalid Codex session ID.")
        args = [self.binary, "exec", "--json", "--skip-git-repo-check", "resume", session_id]
        allow_write = self.workspace_write
        if allow_write is None:
            allow_write = os.environ.get("TELECODE_CODEX_WORKSPACE_WRITE", "")
        if str(allow_write).strip().lower() in ("1", "true", "yes", "on"):
            args += ["-c", "sandbox_mode=workspace-write"]
        return args + ["--", str(text)]

    def send_message(self, session_id, text, delivery="queue"):
        session = self.validate_session(session_id)
        if session is None:
            raise CodexAdapterError("That Codex session is no longer available. Select a current session and resend.")
        try:
            popen_options = {"cwd": session.directory, "stdout": subprocess.PIPE,
                             "stderr": subprocess.PIPE}
            if os.name == "nt":
                popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_options["start_new_session"] = True
            process = subprocess.Popen(self.build_argv(session_id, text), **popen_options)
            stdout, stderr = [], []
            readers = [threading.Thread(target=_read_bounded, args=(process.stdout, stdout), daemon=True),
                       threading.Thread(target=_read_bounded, args=(process.stderr, stderr), daemon=True)]
            for reader in readers:
                reader.start()
            try:
                returncode = process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                _kill_process_tree(process)
                raise
            finally:
                for reader in readers:
                    reader.join(timeout=2)
                process.stdout.close()
                process.stderr.close()
        except FileNotFoundError as exc:
            raise CodexAdapterError("Codex CLI was not found. Install Codex CLI or set CODEX_BIN, then restart TeleCode.") from exc
        except subprocess.TimeoutExpired as exc:
            raise CodexAdapterError("Codex did not finish before the 10-minute timeout.") from exc
        except OSError as exc:
            raise CodexAdapterError(f"Could not start Codex CLI: {exc}") from exc
        output = stdout[0] if stdout else ""
        if returncode:
            detail = (stderr[0] if stderr else output or "Codex exited with an error.").strip().replace("\n", " ")[:500]
            if "no rollout found" in detail.lower() or "thread not found" in detail.lower():
                raise CodexAdapterError("That Codex session no longer exists. Select a current session and resend.")
            raise CodexAdapterError(f"Codex failed: {detail}")
        replies = []
        for line in output.splitlines():
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(event, dict):
                item = event.get("item") or event.get("data") or {}
                if event.get("type") in ("item.completed", "response_item") and isinstance(item, dict):
                    if item.get("type") == "agent_message":
                        text_value = item.get("text")
                        if isinstance(text_value, str):
                            replies.append(text_value)
        return "\n".join(replies).strip() or output.strip() or "Codex completed without a text response."
