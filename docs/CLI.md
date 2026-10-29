# CLI integrations

TeleCode separates two capabilities:

1. **Outbound bridge tools.** Any local MCP client can start `tg_mcp.py` and call
   `tg_send`, `tg_sendfile`, `tg_read`, `tg_status`, `tg_sessions`,
   `tg_select_session`, and `tg_open_session_picker`. This requires only a stdio
   MCP client.
2. **Targeted Telegram-to-session routing.** The listener must be able to enumerate
   sessions, validate a session ID, and inject a prompt into exactly one session.
   Only OpenCode currently has this adapter.

Installing the MCP server does not enable targeted routing for other CLIs. The
listener routes inbound messages through the OpenCode API regardless of which CLI
started the MCP server, so a non-OpenCode client receives replies only when the
agent running in the OpenCode target session calls the MCP tools.

## Support matrix

| Client | Config written by installer | Format | Outbound tools | Targeted routing | Notes |
| --- | --- | --- | --- | --- | --- |
| OpenCode | `~/.config/opencode/opencode.json` | JSON | Yes | Yes | Verified session discovery and prompt delivery. |
| Claude Code | `~/.claude.json` or `~/.claude/settings.json` | JSON | Yes | No | Adapter raises `NotImplementedError`; fails closed. |
| Codex CLI | `~/.codex/config.toml` | TOML | Yes | No | Installer appends a table after parsing existing TOML. |
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
must list sessions from the current home directory. If the target is `(none)`, the
OpenCode service is not reachable or no root session exists in the home directory.

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
installer inserts one before the appended block. Codex receives outbound tools only.

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
