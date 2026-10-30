# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |
| Earlier or unversioned snapshots | No |

Security fixes are applied to the current 0.1.x line. Run the latest tagged release.

## Reporting a vulnerability

Report privately through GitHub Security Advisories for the repository
(`Security` tab, "Report a vulnerability"). Do not open a public issue, discussion,
or pull request that describes an exploitable condition.

Include:

- Affected version or commit.
- The command, configuration, and platform used.
- Reproduction steps with secrets removed.
- Impact: what an attacker gains and which boundary is crossed.
- Whether a workaround exists.

Do not send real bot tokens, chat IDs, session IDs, or message contents. Replace them
with clearly fake values. Acknowledgement and remediation timelines depend on severity
and maintainer availability; this project does not operate a paid response program.

## Threat model

TeleCode assumes a single-user machine where the operating-system account running the
bridge is trusted. It protects the owner chat from unauthorized Telegram users and
limits which local files the agent can send to that chat.

In scope:

- Unauthorized Telegram users attempting to inject prompts or read replies.
- A compromised or malicious Telegram message, caption, filename, or attachment
  attempting to steer the agent or exfiltrate files.
- Local file disclosure through `tg_sendfile` beyond the configured allowlist.
- Duplicate listeners competing for Telegram updates.
- Accidental world-readable credentials or state files.
- Installer writes that corrupt or overwrite an existing CLI configuration.

Out of scope:

- A local user who can read the runtime directory, attach a debugger, replace the
  `opencode` binary, or call the local OpenCode API directly.
- A compromised coding-agent process. The agent is trusted to call MCP tools and can
  send any file that passes the allowlist checks.
- Telegram account takeover or bot token theft outside the host.
- Prompt injection inside repository content, dependencies, or tool output. Inbound
  Telegram content is treated as untrusted input, but the bridge does not sanitize
  model behavior.
- Denial of service against the local host or the Telegram API.

## Authorization

Every update is checked before storage or routing:

- Message and callback chat ID must equal `TG_CHAT_ID` exactly.
- Callback sender ID must also equal `TG_CHAT_ID`.
- Message sender ID must equal `TG_CHAT_ID` when Telegram supplies one. Telegram
  normally supplies `from.id` for private-chat messages; if a message omits it, only
  the chat check applies. Callback queries are always checked on both fields.
- Unauthorized updates are logged and discarded. They are not written to
  `inbox.jsonl` and never enter the injection queue.
- There is no group support. Do not add the bot to a group and do not treat group
  membership as authorization.

The bot answers only `TG_CHAT_ID`; there is no parameter that selects another chat.

## Session routing

Injection targets are validated before use. OpenCode session IDs must match
`ses[0-9A-Za-z_-]{6,80}`; Codex session IDs must be UUID-shaped. Any
selected session is re-verified against the live session list before each
delivery, and a selection that no longer resolves is cleared rather than
routed blindly. Messages are routed to one configured agent at a time
(`TELECODE_AGENT`); the bridge never shells out to more than the configured
agent CLI, and no message content is treated as bridge commands.

Codex inbound routing is experimental. Codex runs in its default read-only sandbox
unless `TELECODE_CODEX_WORKSPACE_WRITE=1` is explicitly set in `telegram.env`. That
opt-in adds `sandbox_mode=workspace-write`, allowing Telegram-originated prompts to
modify files in the selected session's working directory. Telegram messages remain
untrusted input; enable this only when that risk is acceptable. TeleCode never adds
an approval bypass or disables the sandbox. Codex CLI output and execution are
bounded by a 10-minute timeout and a 64 KiB combined captured-output limit.

## Secret handling

`telegram.env` is loaded on every listener or tool call that needs credentials. The
loader enforces:

1. The path exists and is a regular file.
2. It is not a symlink.
3. Mode bits outside `0600` are absent (`st_mode & 0o077 == 0`).
4. The file is owned by the current user on non-Windows platforms.
5. `TG_BOT_TOKEN` and `TG_CHAT_ID` are present.

On Windows, setup removes inherited ACLs from `telegram.env` and grants full
control only to the installing user; CI verifies the resulting ACL. The Windows
loader does not currently re-check ACLs each time it reads the file, so keep the
runtime directory private and avoid changing its ACL after installation.

`TG_BOT_TOKEN` is used only in Telegram Bot API URLs and multipart requests. It is not
written to the inbox, the state files, or MCP responses. Diagnostics go to stderr and
may be captured by systemd. Review journal output before sharing it.

Never commit:

- `telegram.env` or any copy of it.
- `inbox.jsonl`, `files/`, `active-session.json`, or `models-cache.json`.
- Terminal captures containing the token or a chat ID.

Create a dedicated bot for this bridge. Do not reuse a bot that serves other
automation. If a `telegram.env` backup, terminal log, or journal entry ever exposed
the token, rotate it immediately with BotFather (`/revoke`) and update
`telegram.env`; deleting the message or file is not sufficient.

## File send allowlist

`tg_sendfile` accepts a path only when all of these hold:

1. The path resolves to an existing regular file.
2. The original argument is not a symlink.
3. The resolved path equals, or is below, one entry in `TG_SEND_ROOTS`.
4. The resolved path is not `telegram.env`.
5. The resolved path is not below `~/.ssh` or `~/.config/opencode`.
6. The file is at most 49 MB.

`TG_SEND_ROOTS` is read from the process environment first. If it is empty or unset,
the MCP server reads it from `telegram.env`. Entries are separated by `os.pathsep`
(`:` on Linux and macOS). Relative entries are expanded with `~` support and resolved
against the process working directory; prefer absolute paths. An empty allowlist
denies every file.

The deny list is hard-coded and applies even if a deny path is inside an allowed root.
It covers only the listed paths. It does not cover other credential locations such as
`~/.aws`, `~/.config/gh`, browser profiles, or project secrets. Keep `TG_SEND_ROOTS`
narrow, for example a single output directory, rather than a home directory.

Path checks happen before the read. A local attacker who can replace a file between
the check and the read is outside the threat model.

Inbound downloads are a separate path: they are written under
`files/<session-id>/` with sanitized names, an exclusive create (`xb`), and a 20 MB
cap. They are not constrained by `TG_SEND_ROOTS`.

## State file handling

- `os.umask(0o077)` is set at import, so new runtime files are owner-only.
- `active-session.json` and `models-cache.json` use temporary files plus
  `os.replace`; the cache temp file is chmod `0600` before replacement.
- The listener lock file and PID file are created owner-only.
- The installer preserves an existing config file's mode and creates new files with
  `0600`.
- Backups created by the installer contain CLI configuration, not `telegram.env`.
  They may still reveal local paths or other MCP server commands; keep them private.

## Hardening checklist

```sh
# Runtime directory and credentials
RUNTIME="${XDG_CONFIG_HOME:-$HOME/.config}/telegram-bridge"
chmod 700 "$RUNTIME"
chmod 600 "$RUNTIME/telegram.env"
stat -c '%a %U %n' "$RUNTIME/telegram.env"

# Single listener and service state
systemctl --user status telegram-bridge
pgrep -af 'tg_bridge.py listen'

# Review the effective unit hardening
systemctl --user cat telegram-bridge
```

- Keep `TG_SEND_ROOTS` to the smallest useful set of absolute paths.
- Use `ProtectHome=read-only` and explicit `ReadWritePaths` as provided by the unit.
- Run the bridge as the same non-root user that owns the CLI sessions.
- Do not expose the runtime directory over a network share or sync service.
- Do not install the systemd unit and a second manual listener without the lock; the
  lock prevents duplicates, but a manual process will consume updates unpredictably
  if it bypasses the unit.
- Review `git status` before committing to ensure runtime artifacts are not staged.
- Rotate the bot token after any suspected leak, then restart the listener and the
  CLI so both reload `telegram.env`.
- Treat agent output as potentially influenced by untrusted repository content. The
  allowlist is the last line of defense for outbound files, not a content filter.
