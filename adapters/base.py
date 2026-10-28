"""Neutral adapter contract for local coding-agent CLIs."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AgentSession:
    id: str
    title: str
    directory: str = ""


class AgentAdapter(Protocol):
    name: str

    def list_sessions(self) -> list[AgentSession]: ...
    def validate_session(self, session_id: str) -> AgentSession | None: ...
    def send_message(self, session_id: str, text: str, delivery: str = "queue") -> bool: ...
