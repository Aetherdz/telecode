# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to semantic versioning.

## [Unreleased]

### Added

- `telegram_bridge/` package with eight modules (`state`, `util`, `telegram`,
  `agents`, `pickers`, `routing`, `listener`, `cli`).
- Telegram reply and inline keyboard controls now use the Bot API button styles:
  blue for navigation, green for creation actions, and red for Cancel.
- Reply keyboards no longer auto-hide after a button is pressed, while keeping
  Telegram's show/hide keyboard toggle available.
- Session picker offers a validated “Open by ID” action for available workspace sessions.

### Changed

- `tg_bridge.py` is now a thin entry point and forwarding shim that re-exports the
  `telegram_bridge` package; commands, MCP paths, and installed file names are
  unchanged.

### Fixed

- Codex sessions given a name now show that name in Telegram. `thread/list`
  omits threads with no user events, so named sessions fell back to the rollout
  folder name; the adapter now also reads Codex's own `session_index.jsonl`
  thread-name records.
- Codex `/newsession` no longer fails: sessions are created with `thread/start`
  and `thread/name/set` in one app-server process (the rollout file only flushes
  when a mutating call runs in the creating process), and durability is verified
  with `thread/resume` instead of `thread/list`, which omits threads with no user
  events.
- Codex pickers are much faster: paginated `thread/list` and `model/list` pages
  now run inside one app-server process instead of spawning one process per
  page, `validate_session` reads the thread directly instead of re-listing all
  sessions, and app-server shutdown no longer blocks up to ~5s when the process
  ignores stdin EOF and SIGTERM (worst observed picker call went from ~5.1s to
  under 0.7s). Mutating batches keep a patient shutdown so deferred writes can
  flush.
- The persisted active session now records which agent it belongs to, and
  session resolution rejects (and clears) an active session saved for a
  different agent, so a stale cross-agent selection can no longer be targeted
  by mistake. Legacy active-session files without an agent field keep working.
- Cursor session validation now requires a matching local chat metadata entry,
  and queued inbound updates carry their originating agent; queued targets from
  a different or unknown agent fail closed instead of being rerouted.

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
