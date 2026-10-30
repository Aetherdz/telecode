# Agent adapters

The Telegram transport should depend on this small interface, not a particular
CLI. `opencode.py` is the first production adapter. MCP is a tool transport and
does not itself guarantee that a client exposes APIs for enumerating sessions
or injecting a prompt into a chosen session; unsupported operations must be
reported as unavailable rather than guessed.

Cursor CLI and Codex CLI adapters are experimental. Cursor can resume a known
thread but does not expose a documented machine-readable session-list API. Codex
session discovery reads local rollout files and is best-effort. Keep these
limitations explicit; an MCP integration alone does not imply inbound routing.
