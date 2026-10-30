"""Experimental inbound adapter for resuming Codex CLI sessions."""
import json
import itertools
import os
import pathlib
import queue
import re
import subprocess
import threading
import time

from .base import AgentSession

_SESSION_ID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_MAX_ROLLOUT_BYTES = 8 * 1024 * 1024
_LOGIN_WARNING_SENT = False


class CodexAdapterError(RuntimeError):
    """A clear, user-displayable Codex adapter failure."""


def _codex_home():
    return pathlib.Path(os.environ.get("CODEX_HOME") or pathlib.Path.home() / ".codex").expanduser()


class CodexAdapter:
    name = "codex"

    def __init__(self, binary="codex", timeout=600, sessions_root=None,
                 model=None, model_provider=None, workspace=None):
        self.binary = binary
        self.timeout = timeout
        self.sessions_root = pathlib.Path(sessions_root) if sessions_root else _codex_home() / "sessions"
        self.model = str(model or "").strip()
        self.model_provider = str(model_provider or "").strip()
        self.workspace = pathlib.Path(workspace or os.environ.get("CODEX_WORKSPACE") or pathlib.Path.home()).expanduser().resolve()

    def _app_server(self, method, params=None, timeout=45):
        """Make one JSONL RPC to Codex's local app-server without requiring an API token for local metadata."""
        results = self._app_server_batch([(method, params)], timeout=timeout)
        return results[0]

    def _app_server_batch(self, calls, timeout=45):
        """Run JSONL RPCs sequentially against one app-server process.

        Each call is sent only after the previous response arrives; a params
        callable receives the first call's result, so later calls can reference
        earlier results while sharing the same process.
        Some thread mutations (for example thread/name/set) only materialize
        the rollout file when they run in the same app-server process that
        started the thread, so a shared process is required for durable
        session creation.
        """
        output = queue.Queue()
        try:
            process = subprocess.Popen(
                [self.binary, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1,
            )
        except FileNotFoundError as exc:
            raise CodexAdapterError("Codex CLI was not found. Install Codex CLI or set CODEX_BIN.") from exc
        except OSError as exc:
            raise CodexAdapterError(f"Could not start Codex app-server: {exc}") from exc

        def read_output():
            try:
                for line in process.stdout:
                    output.put(line)
            finally:
                output.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        def request(request_id, method, params):
            process.stdin.write(json.dumps({
                "method": method, "id": request_id, "params": params or {},
            }) + "\n")
            process.stdin.flush()
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CodexAdapterError(f"Codex app-server {method} timed out.")
                try:
                    line = output.get(timeout=remaining)
                except queue.Empty as exc:
                    raise CodexAdapterError(f"Codex app-server {method} timed out.") from exc
                if line is None:
                    raise CodexAdapterError(f"Codex app-server exited during {method}.")
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    detail = message["error"].get("message") or "Codex app-server request failed."
                    raise CodexAdapterError(str(detail)[:500])
                return message.get("result") or {}

        try:
            request(1, "initialize", {
                "clientInfo": {"name": "telecode", "title": "TeleCode", "version": "1.0"},
                "capabilities": {"experimentalApi": True},
            })
            process.stdin.write(json.dumps({"method": "initialized", "params": {}}) + "\n")
            process.stdin.flush()
            results = []
            for index, (method, params) in enumerate(calls):
                resolved = params(results[0]) if callable(params) else params
                results.append(request(index + 2, method, resolved))
            return results
        except (BrokenPipeError, OSError) as exc:
            raise CodexAdapterError(f"Codex app-server connection failed: {exc}") from exc
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
            if process.poll() is None:
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
            reader.join(timeout=1)
            try:
                process.stdout.close()
            except OSError:
                pass

    def list_models(self):
        models = []
        cursor = None
        while True:
            params = {"limit": 100, "includeHidden": False}
            if cursor:
                params["cursor"] = cursor
            result = self._app_server("model/list", params, timeout=45)
            for item in result.get("data", []):
                model_id = str(item.get("id") or item.get("model") or "").strip()
                if model_id:
                    models.append({"id": model_id,
                                   "providerID": str(item.get("modelProvider") or "openai"),
                                   "name": str(item.get("displayName") or model_id)})
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return models

    def create_session(self, title):
        title = " ".join(str(title or "").split())
        if not title:
            raise CodexAdapterError("Session name is required.")
        if not self.workspace.is_dir():
            raise CodexAdapterError("Codex workspace does not exist.")
        params = {
            "cwd": str(self.workspace), "approvalPolicy": "never", "sandbox": "read-only",
            "ephemeral": False,
        }
        if self.model:
            params["model"] = self.model
        if self.model_provider:
            params["modelProvider"] = self.model_provider
        try:
            result, _, resumed = self._app_server_batch([
                ("thread/start", params),
                ("thread/name/set", lambda start: {"threadId": str(start.get("thread", {}).get("id") or ""),
                                                   "name": title}),
                ("thread/resume", lambda start: {"threadId": str(start.get("thread", {}).get("id") or ""),
                                                 "approvalPolicy": "never", "sandbox": "read-only"}),
            ])
        except CodexAdapterError as exc:
            detail = str(exc)
            if ("did not return a valid thread" in detail
                    or "not found" in detail or "could not start" in detail.lower()):
                raise
            raise CodexAdapterError(
                "Codex did not persist the new session to disk. "
                "Create a session in Codex first, then select it in TeleCode."
            ) from exc
        thread = result.get("thread") or {}
        sid = str(thread.get("id") or "")
        if not _SESSION_ID_RE.fullmatch(sid):
            raise CodexAdapterError("Codex did not return a valid thread ID.")
        # thread/name/set must share the app-server process with thread/start:
        # the rollout file is only flushed when a mutating call runs in the
        # process that created the thread. thread/resume in the same process
        # proves the rollout was materialized. thread/list cannot verify
        # durability because it omits threads that have no user events yet.
        return AgentSession(sid, title, str(self.workspace), self.name,
                            updated=float(thread.get("updatedAt") or 0))

    def set_session_model(self, session_id, model_id):
        if not _SESSION_ID_RE.fullmatch(str(session_id or "")):
            raise CodexAdapterError("Invalid Codex session ID.")
        return self._app_server("thread/settings/update", {
            "threadId": session_id, "model": str(model_id),
        })

    def current_model(self, session_id):
        result = self._app_server("thread/read", {"threadId": session_id})
        return str((result.get("thread") or {}).get("model") or "")

    def list_sessions(self):
        found = {}
        try:
            paths = itertools.islice(self.sessions_root.rglob("rollout-*.jsonl"), 5000) if self.sessions_root.is_dir() else ()
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
        # Merge both sources: rollouts can have richer cwd coverage, while the
        # app-server database may contain newer threads without rollout files.
        sessions_by_id = dict(found)
        try:
            cursor = None
            for _ in range(50):
                params = {"limit": 100, "sortKey": "updated_at"}
                if cursor:
                    params["cursor"] = cursor
                result = self._app_server("thread/list", params)
                for thread in result.get("data", []):
                    sid = str(thread.get("id") or "")
                    cwd = str(thread.get("cwd") or "")
                    if not _SESSION_ID_RE.fullmatch(sid) or not cwd:
                        continue
                    previous = sessions_by_id.get(sid)
                    title = str(thread.get("name") or thread.get("preview") or
                                (previous.title if previous else pathlib.Path(cwd).name) or "Codex session")
                    try:
                        updated = max(float(thread.get("updatedAt") or 0),
                                      previous.updated if previous else 0)
                    except (TypeError, ValueError, OverflowError):
                        updated = previous.updated if previous else 0
                    sessions_by_id[sid] = AgentSession(sid, title[:80], cwd, self.name, updated)
                cursor = result.get("nextCursor")
                if not cursor:
                    break
        except CodexAdapterError:
            pass
        return sorted(sessions_by_id.values(), key=lambda session: session.updated, reverse=True)[:100]

    def validate_session(self, session_id):
        if not _SESSION_ID_RE.fullmatch(str(session_id or "")):
            return None
        return next((session for session in self.list_sessions() if session.id == session_id), None)

    def build_argv(self, session_id, text):
        if not _SESSION_ID_RE.fullmatch(str(session_id or "")):
            raise CodexAdapterError("Invalid Codex session ID.")
        # Avoid opening a second writer with `exec resume`; Codex's queue
        # command targets the existing thread directly, including a live TUI.
        return [self.binary, "queue", "--thread", session_id, "--message", str(text)]

    def send_message(self, session_id, text, delivery="queue"):
        session = self.validate_session(session_id)
        if session is None:
            raise CodexAdapterError("That Codex session is no longer available. Select a current session and resend.")
        try:
            result = subprocess.run(self.build_argv(session_id, text), cwd=session.directory,
                                    capture_output=True, text=True,
                                    timeout=min(float(self.timeout), 30), check=False)
        except FileNotFoundError as exc:
            raise CodexAdapterError("Codex CLI was not found. Install Codex CLI or set CODEX_BIN, then restart TeleCode.") from exc
        except subprocess.TimeoutExpired as exc:
            raise CodexAdapterError("Codex did not queue the message before the timeout.") from exc
        except OSError as exc:
            raise CodexAdapterError(f"Could not start Codex CLI: {exc}") from exc
        output = (result.stdout or "").strip()
        if result.returncode:
            detail = (result.stderr or output or "Codex exited with an error.").strip().replace("\n", " ")[:500]
            if "no rollout found" in detail.lower() or "thread not found" in detail.lower():
                raise CodexAdapterError("That Codex session no longer exists. Select a current session and resend.")
            raise CodexAdapterError(f"Codex failed: {detail}")
        try:
            auth = subprocess.run([self.binary, "login", "status"], capture_output=True,
                                  text=True, timeout=8, check=False)
            auth_text = ((auth.stdout or "") + " " + (auth.stderr or "")).strip()
            if auth.returncode or "not logged in" in auth_text.lower():
                global _LOGIN_WARNING_SENT
                if not _LOGIN_WARNING_SENT:
                    _LOGIN_WARNING_SENT = True
                    return (f"{output or 'Message queued for the selected Codex session.'}\n"
                            "Codex is not logged in, so it cannot generate a reply yet. "
                            "Sign in with `codex login`; if this queued message is not picked up after sign-in, resend it.")
        except (OSError, subprocess.TimeoutExpired):
            pass
        return output or "Message queued for the selected Codex session."
