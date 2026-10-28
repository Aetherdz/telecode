"""Claude Code capability note / future adapter stub.

Claude Code supports MCP servers, but MCP is not a session-routing API. Until
there is a stable supported interface to list Claude Code sessions and target
one for prompt delivery, this adapter intentionally fails closed.
"""


class ClaudeCodeAdapter:
    name = "claude-code"

    def list_sessions(self):
        raise NotImplementedError(
            "Claude Code MCP integration is available for outbound bridge tools; "
            "targeting a selected Claude Code session is not implemented."
        )

    def validate_session(self, session_id):
        return None

    def send_message(self, session_id, text, delivery="queue"):
        raise NotImplementedError("Targeted Claude Code session delivery is not implemented")
