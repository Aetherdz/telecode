"""OpenCode CLI adapter; delegates to its local API through the CLI."""
import json
import pathlib
import subprocess
import urllib.parse

from .base import AgentSession


class OpenCodeAdapter:
    name = "opencode"

    def __init__(self, binary="opencode", directory=None):
        self.binary = binary
        self.directory = pathlib.Path(directory or pathlib.Path.home()).resolve()

    def _api(self, method, path, body=None):
        cmd = [self.binary, "api", method, path]
        if body is not None:
            cmd += ["-d", json.dumps(body)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode:
            raise RuntimeError("OpenCode API request failed")
        return json.loads(result.stdout) if result.stdout.strip() else None

    def list_sessions(self):
        path = "/api/session?order=desc&limit=100&parentID=null&directory=" + urllib.parse.quote(str(self.directory))
        result = self._api("get", path)
        items = result.get("data", []) if isinstance(result, dict) else result or []
        return [AgentSession(str(item["id"]), str(item.get("title") or "Untitled"),
                             str(item.get("directory") or self.directory))
                for item in items if isinstance(item, dict) and item.get("id")
                and not item.get("parentID") and not (item.get("time") or {}).get("archived")]

    def validate_session(self, session_id):
        return next((session for session in self.list_sessions() if session.id == session_id), None)

    def send_message(self, session_id, text, delivery="queue"):
        if not session_id.startswith("ses"):
            return False
        result = self._api("post", f"/api/session/{urllib.parse.quote(session_id, safe='')}/prompt",
                           {"text": text, "delivery": delivery})
        return result is not False
