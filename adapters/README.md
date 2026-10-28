# Agent adapters

The Telegram transport should depend on this small interface, not a particular
CLI. `opencode.py` is the first production adapter. MCP is a tool transport and
does not itself guarantee that a client exposes APIs for enumerating sessions
or injecting a prompt into a chosen session; unsupported operations must be
reported as unavailable rather than guessed.

Claude Code can use the bridge MCP tools for outbound Telegram replies. Its
session adapter is intentionally a fail-closed stub until a stable supported
session targeting interface is available; do not claim Telegram-to-Claude
session injection based on MCP support alone.
