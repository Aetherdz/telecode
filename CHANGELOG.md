# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to semantic versioning.

## [Unreleased]

### Fixed

- The interactive CLI selector no longer overwrites its own header: redraws move
  up exactly the number of menu lines, and cancellation restores the cursor.
- The selector renders as an aligned box with numbered rows, detection labels,
  arrow-key navigation, direct 1-9 jumps, and a plain numbered fallback.
- `telecode` with no arguments now opens the documented Setup/Exit menu instead
  of printing a usage error; non-interactive runs still print usage and exit 2.
- The installer no longer fails on machines without a reachable systemd user
  bus (Docker, WSL, macOS). `--enable` explains the situation and suggests
  `telecode listen`, while guided setup completes without enabling a service.
- Setup prompts treat EOF and Ctrl-C as a clean cancellation instead of raising
  a traceback, and the manual-setup hint prints the real runtime path.
- The session picker now uses a short, separator-based header followed by a
  blank line, so chat-list previews no longer read as one concatenated line.
- Control buttons no longer re-send the main keyboard or a status sentence after
  every action. Session selection and session creation send one confirmation,
  cancels close silently (except the name prompt), and `Help`/`/start` send one
  combined keyboard message instead of two messages.
- Documentation no longer claims a Rich dependency or a local browser wizard
  that the project does not ship.

## [0.1.0] - 2026-10-28

First public release. TeleCode provides an owner-only Telegram control surface for
local coding-agent CLI sessions, with verified targeted routing for OpenCode and
outbound MCP tools for other MCP-capable clients.

### Added

- Telegram listener with long polling, owner authorization, and prompt injection
  into the selected local OpenCode session.
- Persistent, text-only reply keyboard with `Sessions`, `Current session`, `Models`,
  and `Help`.
- `/session` paginated session picker, 8 sessions per page, with previous, next, and
  cancel controls and duplicate-title disambiguation.
- `/current` active-session report with fallback discovery and pinned-session mode.
- `/models` inline picker: provider list, model pages of 8, current-model marker,
  back and close controls.
- Model switching through `POST /api/session/{sessionID}/model` with a persisted
  server-side selection; catalogue loaded from `GET /api/model`.
- Inbound document and photo handling, stored per session under `files/<session-id>/`
  with sanitized names and a 20 MB cap.
- `/files` listing of up to 20 received files for the active session.
- MCP stdio server exposing `tg_send`, `tg_sendfile`, `tg_read`, `tg_status`,
  `tg_sessions`, `tg_select_session`, and `tg_open_session_picker`.
- OpenCode adapter with verified session listing, validation, and targeted delivery.
- Fail-closed Claude Code adapter that refuses session targeting while still allowing
  outbound MCP tools.
- Codex TOML integration that preserves existing content and appends a
  `[mcp_servers.telegram-bridge]` table only after parsing succeeds.
- Interactive CLI installer with detection for OpenCode, Claude Code, Codex, Cursor,
  Gemini CLI, Cline, Roo Code, Continue, Aider, and Amazon Q; manual MCP fallback for
  other clients.
- Backup-first installer writes: timestamped backup, confirmation prompt, `mkstemp`,
  `fsync`, `os.replace`, directory `fsync`, and mode preservation.
- Optional systemd user service with `NoNewPrivileges`, `PrivateTmp`,
  `ProtectSystem=full`, `ProtectHome=read-only`, and explicit write paths.
- Project site assets: SVG wordmark and mark, terminal wordmark, and HTML wordmark.
- Documentation set: installation, CLI integrations, buttons and commands, model
  switching, architecture, security policy, contributing guide, and changelog.
- Stdlib `unittest` suite covering session labels, atomic state, file allowlists,
  fail-closed adapters, stale session buttons, Codex TOML handling, JSON schema
  refusal, and mode-preserving writes.

### Fixed

- Session switches no longer reroute messages or attachments that were already
  queued; the target is captured at receive time and preserved.
- Stale session-picker labels are handled as controls instead of being forwarded to
  the agent as prompts.
- Duplicate listener instances are prevented with a non-blocking `fcntl.flock`.
- Stale `active-session.json` selections are removed instead of routing into another
  project directory.
- A failed `steer` delivery is retried once with `queue` delivery before the update is
  considered failed.
- Model picker selections validate their indices and report an expired menu instead
  of switching to the wrong entry.
- Installer refuses malformed JSON, invalid TOML, unsupported schemas, and existing
  `telegram-bridge` entries without modifying the target file.

### Security

- Owner enforcement compares the configured chat ID and the sender ID; callback
  queries require both to match.
- `telegram.env` must be a regular file, mode `0600`, owned by the current user, and
  not a symlink.
- Session IDs are validated with `ses[0-9A-Za-z_-]{6,80}` and URL-quoted before use.
- `tg_sendfile` is restricted to `TG_SEND_ROOTS` and refuses `telegram.env`, `~/.ssh`,
  and `~/.config/opencode` even when those paths fall inside an allowed root.
- Session state and model cache writes are atomic and owner-only; the process sets
  `umask 077`.
- The systemd unit runs with a hardened filesystem and privilege profile.
- Documentation calls out token rotation after any `telegram.env` exposure and
  instructs reporters to use a private advisory rather than a public issue.
