<p align="center"><img src="assets/brand/telecode-wordmark.svg" alt="TeleCode" width="720"></p>

# TeleCode

TeleCode is an owner-only Telegram control surface for local coding-agent CLI sessions.
It routes Telegram messages and attachments into the session you select, and lets the
agent reply through MCP tools.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![MCP](https://img.shields.io/badge/MCP-stdio-informational.svg)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS-lightgrey.svg)

## Why TeleCode

Coding-agent CLIs are excellent at long-running local work, but they keep you at the
terminal. TeleCode gives one owner chat a narrow, explicit control channel: pick a
session, send text or files, and receive the agent's output without exposing a shell
or a web endpoint. There is no prompt router and no second model in the path. The
message goes to the local session, and the agent decides how to answer.

## Features

- Owner-only listener: both the chat ID and the sender ID must match the configured
  owner before a message is stored or routed.
- Persistent, text-only reply keyboard with session, current-session, model, and help
  controls.
- Paginated session picker that switches a single active target without editing
  environment files or source.
- Paginated inline model picker that applies a model switch to the active session
  through the local OpenCode API.
- Inbound text, documents, and photos routed into the selected session; attachments
  are captured against the session that was active when they arrived.
- Outbound MCP tools for the agent: `tg_send`, `tg_sendfile`, `tg_read`,
  `tg_status`, `tg_sessions`, `tg_select_session`, `tg_open_session_picker`.
- Backup-first installer with atomic writes, mode preservation, and an explicit
  confirmation before any CLI config is changed.
- Stdlib-only Python 3.11+ runtime with no build step; optional systemd user service
  for autostart.

## How it works

```mermaid
flowchart LR
    A[Owner chat] -->|text or attachment| B[tg_bridge.py listener]
    B --> C{Active session}
    C -->|opencode api POST prompt| D[Local CLI session]
    D -->|MCP stdio| E[tg_mcp.py]
    E -->|tg_send / tg_sendfile| A
```

The listener long-polls Telegram. Owner messages are appended to `inbox.jsonl` and
queued for injection into the active session. The agent reaches the owner through
the MCP server, which runs as a stdio subprocess of the CLI.

## Quick start

```sh
git clone https://github.com/aetherdz/telecode.git
cd telecode
./install.sh
```

The installer copies the runtime into
`${XDG_DATA_HOME:-$HOME/.local/share}/telegram-bridge`, creates
`${XDG_CONFIG_HOME:-$HOME/.config}/telegram-bridge/telegram.env` on first run, and
offers to configure a detected CLI. Edit `telegram.env` and set `TG_BOT_TOKEN` and
`TG_CHAT_ID` before starting.

Then restart the coding-agent CLI so it loads the MCP server, and press `/start`
in the Telegram chat. The listener is started by the MCP server when
`TG_AUTOSTART=1` (default), or by the systemd unit if you enabled it.

See [docs/INSTALL.md](docs/INSTALL.md) for the full sequence, including the
credential checks the installer performs.

## Commands and buttons

| Input | Type | Effect |
| --- | --- | --- |
| `Sessions` | Reply keyboard | Same as `/session`: send the paginated session picker. |
| `Current session` | Reply keyboard | Same as `/current`: report the active session title and ID. |
| `Models` | Reply keyboard | Same as `/models`: send the inline provider/model picker. |
| `Help` | Reply keyboard | Same as `/help`: restore the keyboard and print command help. |
| `/session` | Slash command | Paginated session picker, 8 sessions per page. |
| `/current` | Slash command | Active target, resolved through discovery if unset. |
| `/models` | Slash command | Inline model picker; the switch applies to the active session. |
| `/files` | Slash command | Up to 20 received files for the active session, newest first. |
| `/help`, `/start` | Slash command | Restore the persistent keyboard and print help. |

Buttons are exact-match English text. Successfully routed messages do not generate a
separate acknowledgement, so the chat stays focused on the agent's replies. Any
other text is routed to the active session.
Full semantics are in [docs/BUTTONS.md](docs/BUTTONS.md).

## Model switching

`/models` loads the catalogue from `GET /api/model` through the local
`opencode api` command. Choosing a model calls
`POST /api/session/{sessionID}/model` with
`{"model": {"id": "...", "providerID": "..."}}`. The selection is stored in the
session by the OpenCode server and applies to subsequent turns. The bridge uses a
local cache only when the catalogue request fails.

See [docs/MODELS.md](docs/MODELS.md).

## Supported CLIs

| CLI | Outbound MCP tools | Targeted Telegram-to-session routing |
| --- | --- | --- |
| OpenCode | Yes | Yes, verified |
| Claude Code | Yes | No; adapter fails closed |
| Cursor | Yes | No |
| Gemini CLI | Yes | No |
| Cline | Yes | No |
| Roo Code | Yes | No |
| Continue | Yes, manual config | No |
| Aider | Yes, manual config | No |
| Amazon Q Developer | Yes | No |
| Codex CLI | Yes | No |

Targeted routing requires a stable, supported session-listing and prompt-delivery
API. MCP support alone does not provide one. Configuration paths and exact snippets
are in [docs/CLI.md](docs/CLI.md).

## Security

Only the configured owner chat is always checked; sender ID is checked when present, and callbacks require both. `telegram.env` must be a
regular file, mode `0600`, owned by the current user, and not a symlink.
`tg_sendfile` is limited to `TG_SEND_ROOTS` and refuses a hard deny list. The
listener enforces a single instance with `fcntl.flock`.

Read [SECURITY.md](SECURITY.md) for the threat model, reporting process, and
hardening checklist.

## Documentation

- [Installation](docs/INSTALL.md): prerequisites, credential setup, service install.
- [CLI integrations](docs/CLI.md): per-client config paths, snippets, verification.
- [Buttons and commands](docs/BUTTONS.md): keyboard behavior and pagination.
- [Models](docs/MODELS.md): catalogue, switching, failure modes, privacy.
- [Architecture](docs/ARCHITECTURE.md): components, state files, concurrency.
- [Contributing](CONTRIBUTING.md): development workflow and review checklist.
- [Changelog](CHANGELOG.md): release history.
- [Project website](index.html): landing page served by GitHub Pages.

## Development

```sh
make check
make test
```

The Makefile defines two convenience targets:

| Target | Command | Purpose |
| --- | --- | --- |
| `make check` | Python compile, shell syntax, and site JS/HTML checks | Static checks for the runtime, installer, and site. |
| `make test` | `python3 -m unittest discover -s tests -v` | Run the full test suite. |

`make check` does not run the test suite or a general-purpose linter. Run `make test`
before sending a change.

## Website

The project website is the static landing page at [index.html](index.html), published
at the GitHub Pages address <https://aetherdz.github.io/telecode/>. The repository
root is the Pages source.

## License

MIT. See [LICENSE](LICENSE).
