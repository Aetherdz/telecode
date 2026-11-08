# Agent adapters

The Telegram transport should depend on this small interface, not a particular
CLI. `opencode.py` is the first production adapter. MCP is a tool transport and
does not itself guarantee that a client exposes APIs for enumerating sessions
or injecting a prompt into a chosen session; unsupported operations must be
reported as unavailable rather than guessed.

Cursor CLI and Codex CLI adapters are experimental. Cursor's model catalog is
queried from `agent models`; session discovery reads local Cursor metadata because
its CLI does not expose a documented machine-readable list command. Codex reads
local rollouts and falls back to the app-server `thread/list` API; delivery uses
`codex queue` so it targets an existing thread without opening a competing writer.
An empty Codex app-server thread is not durable until it has a turn, so create new
Codex sessions in Codex itself before selecting them in TeleCode.

Hermes Agent (`hermes.py`) adapter connects to Nous Research's Hermes CLI, scanning
`~/.hermes/sessions` (JSON and JSONL) or `~/.hermes/state.db`, and resumes chats headlessly
via `hermes chat --resume <id> -q <text>`.

Google Antigravity (`antigravity.py`) adapter connects to the Antigravity CLI (`agy`),
enumerating active conversations from `~/.gemini/antigravity-cli/conversation_summaries.db`,
and executing non-interactive turns with `agy --conversation <id> --dangerously-skip-permissions --print <text>`.
