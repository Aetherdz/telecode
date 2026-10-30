# Architecture and roadmap

## Adapter contract

Keep Telegram polling, owner authorization, keyboard UX, and file routing
independent from coding-agent session operations. Each agent adapter should
provide:

- `list_sessions()` returning stable IDs, display names, and working directories.
- `validate_session(id)` ensuring it still exists and is within configured scope.
- `send_message(id, text, delivery)` delivering only to the selected session.
- capability metadata for session listing, prompt delivery, and file access.

## Planned

1. Move hard-coded OpenCode CLI calls behind an adapter interface.
2. Claude Code can register the outbound Telegram MCP tools; add inbound session
   routing only when a supported session-targeted API is available. Do not infer
   equivalence from MCP support alone.
3. Add adapters for other MCP-enabled agent CLIs where APIs permit explicit
   session-targeted delivery.
4. Add unit tests for owner filtering, keyboard routing, session switching,
   pagination, file-path allowlists, and duplicate listener prevention.
5. Add a CI workflow for Python syntax, tests, lint, and secret scanning.

## Interaction behavior

The Telegram keyboard is persistent. `/session` opens a paginated list; choosing
one session stores it as the active target. `New session` asks for
a title, creates a root OpenCode session, verifies it, and selects it. Subsequent
messages and attachments are bound to the session selected when received, so
switching sessions does not silently reroute queued messages. `/current` reports
the active ID.
