# CLI integrations

TeleCode separates two capabilities:

1. **Outbound bridge tools.** Any local MCP client can start `tg_mcp.py` and call
   `tg_send`, `tg_sendfile`, `tg_read`, `tg_status`, `tg_sessions`,
   `tg_select_session`, and `tg_open_session_picker`. This requires only a stdio
   MCP client.
2. **Targeted Telegram-to-session routing.** The listener must be able to enumerate
   sessions, validate a session ID, and inject a prompt into exactly one session.
   OpenCode and Claude Code are supported; Codex CLI routing is experimental.

Installing an MCP server does not itself enable targeted routing. Configure
`TELECODE_AGENT` to select a supported inbound adapter; other MCP clients receive
outbound Telegram tools only.

## Support matrix

| Client | Config written by installer | Format | Outbound tools | Targeted routing | Notes |
| --- | --- | --- | --- | --- | --- |
| OpenCode | `~/.config/opencode/opencode.json` | JSON | Yes | Yes | Verified session discovery and prompt delivery. |
| Claude Code | `~/.claude.json` or `~/.claude/settings.json` | JSON | Yes | Yes | Headless `claude --resume` adapter (`TELECODE_AGENT=claude-code`). |
| Codex CLI | `~/.codex/config.toml` | TOML | Yes | Experimental | Inbound via `TELECODE_AGENT=codex`; requires 0.166.0+. |
| Cursor | `~/.cursor/mcp.json` | JSON | Yes | No | No session API used. |
| Gemini CLI | `~/.gemini/settings.json` | JSON | Yes | No | No session API used. |
| Cline | `~/.vscode/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` | JSON | Yes | No | VS Code global storage path. |
| Roo Code | `~/.vscode/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json` | JSON | Yes | No | VS Code global storage path. |
| Amazon Q Developer | `~/.aws/amazonq/mcp.json` | JSON | Yes | No | No session API used. |
| Continue | `~/.continue/config.json` or `~/.continue/config.yaml` | JSON/YAML | Manual | No | Installer does not edit these formats. |
| Aider | `~/.aider.conf.yml` | YAML | Manual | No | Installer does not edit YAML. |
| Other MCP client | none | any | Manual | No | Installer prints the command to register. |

Detection uses `shutil.which` for each executable plus the existence of known
config files. A client is offered only when one of the two is present.

In a terminal, the setup selector moves with the up/down arrows and confirms
with Enter; press `q` to cancel. If the terminal does not support raw key input,
the selector falls back to a numbered prompt.

## Shared registration values

The installer computes two values:

- **Command:** the Python interpreter running the installer
  (`sys.executable`, overridable with `TELEGRAM_BRIDGE_PYTHON`) followed by
  `<app-dir>/tg_mcp.py`.
- **Environment:** `TELEGRAM_BRIDGE_HOME=<runtime-dir>` only.

Defaults:

```text
app dir      ${XDG_DATA_HOME:-$HOME/.local/share}/telegram-bridge
runtime dir  ${XDG_CONFIG_HOME:-$HOME/.config}/telegram-bridge
```

The installer writes JSON entries with `env` as the inline environment map. It does
not add `TG_SEND_ROOTS`; set that variable in `telegram.env` or add it manually to
the stanza. Example templates in `config/` show both variables and use a `.venv`
interpreter path for some clients, which is only valid if you created that virtual
environment.

## OpenCode

Config path: `~/.config/opencode/opencode.json`.

Installer output (server key `telegram-bridge`):

```json
{
  "mcp": {
    "servers": {
      "telegram-bridge": {
        "type": "local",
        "command": ["/usr/bin/python3", "/home/USER/.local/share/telegram-bridge/tg_mcp.py"],
        "environment": {
          "TELEGRAM_BRIDGE_HOME": "/home/USER/.config/telegram-bridge"
        }
      }
    }
  }
}
```

The example template [config/opencode.example.json](../config/opencode.example.json)
uses the server key `telegram` and includes `TG_SEND_ROOTS`. Either server key is
valid to OpenCode; the installer refuses to write when `telegram-bridge` already
exists, and the example will not collide unless you copy it over a generated file.

The listener calls the OpenCode CLI binary. Resolution order:

1. `OPENCODE_BIN` from `telegram.env`, if set.
2. `~/.opencode/bin/opencode`, if present.
3. `opencode` from `PATH`.

Requests are executed as `opencode api <method> <path> [-d <json>]`. The command
wraps the local HTTP API; the bridge does not open a socket directly.

Verification:

```sh
TELEGRAM_BRIDGE_HOME="$HOME/.config/telegram-bridge" telecode status
```

The output must show a listener state and an inject target. In Telegram, `/session`
lists root sessions from every project directory, not only the home directory. If
the target is `(none)`, the configured agent is not reachable or no root session
exists.

## Choosing the routing agent

Inbound routing is adapter-based. Set `TELECODE_AGENT` in `telegram.env`:

| Value | Behavior |
| --- | --- |
| `opencode` (default) | Route prompts through the OpenCode HTTP API. |
| `claude-code` | Resume a Claude Code session headlessly with `claude --resume <id> --print`. |
| `codex` | Resume a Codex CLI session (experimental; see below). |
| `cursor` | Resume a known Cursor Agent session ID headlessly (experimental; see below). |
| unset / `auto` | Prefer Cursor Agent when `agent` is on `PATH`; otherwise OpenCode. |

Claude Code sessions are listed from the local transcript store
(`~/.claude/projects/*/*.jsonl`); their IDs are UUIDs and are validated before
use. Outbound MCP tools (`tg_send`, `tg_sendfile`, `tg_read`, `tg_status`)
behave identically regardless of the selected agent.

## Claude Code

Config paths, in preference order:

- `~/.claude.json`
- `~/.claude/settings.json`

The installer asks which scope to modify when both parent directories exist, then
writes:

```json
{
  "mcpServers": {
    "telegram-bridge": {
      "type": "stdio",
      "command": "/usr/bin/python3",
      "args": ["/home/USER/.local/share/telegram-bridge/tg_mcp.py"],
      "env": {
        "TELEGRAM_BRIDGE_HOME": "/home/USER/.config/telegram-bridge"
      }
    }
  }
}
```

Template: [config/claude-code.example.json](../config/claude-code.example.json).

Claude Code can deliver outbound replies and read queued owner messages. It cannot
be selected as the inbound Telegram target: `adapters/claude_code.py` deliberately
raises `NotImplementedError` for session listing and delivery. This is a documented
capability limit, not a configuration error.

## Codex CLI

Config path: `~/.codex/config.toml`.

The installer parses the existing TOML first, rejects malformed files, rejects an
existing `[mcp_servers.telegram-bridge]` table, and appends:

```toml
[mcp_servers.telegram-bridge]
command = "/usr/bin/python3"
args = ["/home/USER/.local/share/telegram-bridge/tg_mcp.py"]

[mcp_servers.telegram-bridge.env]
TELEGRAM_BRIDGE_HOME = "/home/USER/.config/telegram-bridge"
```

Existing content is preserved. If the file does not end with a newline, the
installer inserts one before the appended block. For inbound routing, set
`TELECODE_AGENT=codex` and ensure the listener runs as the same OS user that owns
the Codex sessions. `CODEX_BIN` can override the `codex` executable.

**Minimum version: Codex CLI 0.166.0.** This is the exact version whose
`codex exec --help` and `codex exec resume --help` were checked for this adapter.
Codex inbound routing is experimental and has not yet been tested against a real
user installation.

The adapter best-effort scans `$CODEX_HOME/sessions` (default `~/.codex/sessions`)
for `rollout-*.jsonl` files and reads `session_meta.payload.id` and `cwd`. It resumes
the selected session in its recorded working directory using argv equivalent to
`codex exec --json --skip-git-repo-check resume SESSION_ID -- PROMPT`. `--json`
produces newline-delimited JSON events. `--skip-git-repo-check` allows resuming
outside a Git repository; `--` separates the Telegram prompt from CLI options.
Malformed or oversized rollout files are skipped; an unreadable session index
degrades to an empty listing.

By default Codex retains its read-only sandbox. To explicitly grant workspace write
access, set `TELECODE_CODEX_WORKSPACE_WRITE=1` in `telegram.env`; this adds
`-c sandbox_mode=workspace-write`. This trusts Telegram-originated instructions to
modify files in the selected working directory. Do not use it for untrusted chats.
No approval bypass or sandbox-disabling option is added.

Verification assumptions: these CLI flags and prompt placement were checked using
the official 0.166.0 Linux package; a nonexistent UUID reached the CLI's “no rollout
found” response without authentication or model execution. Official OpenAI
non-interactive docs confirm `exec`, `resume`, `--json` JSONL output, and the
read-only default/workspace-write sandbox guidance. The rollout directory/metadata
shape was cross-checked against Codex source and examples, but is not a stable
public session-listing API; session discovery is therefore best-effort.

## Cursor

Config path: `~/.cursor/mcp.json`.

```json
{
  "mcpServers": {
    "telegram-bridge": {
      "command": "/usr/bin/python3",
      "args": ["/home/USER/.local/share/telegram-bridge/tg_mcp.py"],
      "env": {
        "TELEGRAM_BRIDGE_HOME": "/home/USER/.config/telegram-bridge"
      }
    }
  }
}
```

Template: [config/cursor.example.json](../config/cursor.example.json).

### Cursor Agent inbound routing

Cursor's CLI documents resuming a thread with `agent --resume <thread-id>` and
non-interactive output with `--print`. Set `TELECODE_AGENT=cursor` and
`CURSOR_WORKSPACE` to the existing project directory associated with that thread;
`CURSOR_AGENT_BIN` can override the CLI executable (default `agent`). The adapter
runs the CLI in that workspace and returns its text response to Telegram. Keep
Cursor authenticated as the same OS user that runs the listener.

TeleCode creates new chats with Cursor's documented `agent create-chat` command;
the requested label is kept in TeleCode's active-session state because that command
does not accept a title. Cursor's documented `agent ls` command is interactive, so
TeleCode best-effort reads `~/.cursor/chats/*/*/meta.json` to list local chats
across projects, then resumes each session in its recorded workspace. This is an
undocumented local format: malformed, oversized, and symlinked entries are skipped.
When Cursor has no title in metadata, TeleCode uses a short excerpt from the first
user prompt in the local transcript (bounded read); otherwise it labels the chat
"Untitled Cursor chat". **Open by ID** remains available as a fallback. New chats
use `CURSOR_WORKSPACE`.
This integration is experimental and has been smoke-tested with a real CLI install.
Cursor headless mode has full write access; Telegram messages can therefore cause
workspace edits.

## Gemini CLI

Config path: `~/.gemini/settings.json`.

```json
{
  "mcpServers": {
    "telegram-bridge": {
      "command": "/usr/bin/python3",
      "args": ["/home/USER/.local/share/telegram-bridge/tg_mcp.py"],
      "env": {
        "TELEGRAM_BRIDGE_HOME": "/home/USER/.config/telegram-bridge"
      }
    }
  }
}
```

Template: [config/gemini-cli.example.json](../config/gemini-cli.example.json).

## Cline

Config path:
`~/.vscode/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`.

Stanza shape is the same as Cursor. Template:
[config/cline.example.json](../config/cline.example.json).

## Roo Code

Config path:
`~/.vscode/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json`.

Stanza shape is the same as Cursor. Template:
[config/roo-code.example.json](../config/roo-code.example.json).

## Amazon Q Developer

Config path: `~/.aws/amazonq/mcp.json`.

Stanza shape is the same as Cursor. Template:
[config/amazon-q.example.json](../config/amazon-q.example.json).

## Continue

Config paths:

- `~/.continue/config.json`
- `~/.continue/config.yaml`

The installer detects Continue but does not modify either file. Register the stdio
server manually using Continue's MCP configuration. Use the shared command and
environment values above; no Continue-specific bridge code exists.

## Aider

Config path: `~/.aider.conf.yml`.

The installer detects Aider but does not edit YAML. Aider must support the MCP
transport in your installed version for outbound tools to work; otherwise configure
a dedicated adapter or hook. Targeted routing is not available.

## Other MCP clients

Choose "Other MCP client" in the installer. It prints the exact command and runtime
path and changes no files:

```sh
/usr/bin/python3 /home/USER/.local/share/telegram-bridge/tg_mcp.py
```

Set `TELEGRAM_BRIDGE_HOME` in the client's environment block to the runtime
directory. Without it, the MCP server falls back to
`${XDG_CONFIG_HOME:-$HOME/.config}/telegram-bridge`.

## Manual verification of the MCP server

The server speaks newline-delimited JSON-RPC over stdio. A minimal check:

```sh
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | TELEGRAM_BRIDGE_HOME="$HOME/.config/telegram-bridge" \
      python3 /home/USER/.local/share/telegram-bridge/tg_mcp.py
```

Expect an `initialize` result and a tool list containing the seven tools. Startup
also attempts to start the listener unless `TG_AUTOSTART` is `0`, `false`, `off`, or
`no`. Logs go to stderr; stdout carries protocol frames only.

## Installer behavior and limits

- It prompts for a numeric selection. The prompt mentions arrow keys, but selection
  is by number; `q` cancels.
- It prints the target path and the MCP command, then asks for `y` confirmation.
- Existing files are copied to `<name>.telegram-bridge.bak.<timestamp>.<pid>` in the
  same directory before writing.
- Writes use `mkstemp`, `fsync`, `os.replace`, and a directory `fsync`. The existing
  file mode is preserved; a new file is created with mode `0600`.
- It refuses to overwrite an existing `telegram-bridge` entry and leaves the file
  unchanged on parse or schema errors.
- Restart the client after a successful write. A running process does not reload its
  MCP configuration.
