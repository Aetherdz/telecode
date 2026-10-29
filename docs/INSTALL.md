# Installation and startup

## Supported platforms

The guided installer requires Python 3.11+ and is supported on Linux with
systemd user services. macOS and Windows are not currently supported by the
guided installer.

## 1. Prepare credentials

Create your bot with Telegram's official **@BotFather** and copy the token. Keep
the token secret; never give it to @Getmyid_bot. For the numeric owner chat ID,
message **@Getmyid_bot** and copy the ID, or select automatic detection during
setup and send `/start` to your own bot. TeleCode never contacts Telegram until
you provide the token and explicitly start ID detection or the listener.

```sh
chmod 600 telegram.env
```

Keep the runtime directory outside public repositories. Set `TG_SEND_ROOTS`
to the one or more folders from which the agent is allowed to send files,
separated by `:` on Linux/macOS.

## 2. OpenCode MCP

Register the local MCP server in OpenCode's config:

```json
{
  "mcp": {
    "servers": {
      "telegram": {
        "type": "local",
        "command": ["python3", "/absolute/path/to/tg_mcp.py"],
        "environment": {
          "TELEGRAM_BRIDGE_HOME": "/absolute/path/to/runtime"
        }
      }
    }
  }
}
```

On OpenCode startup, the MCP server starts the listener when `TG_AUTOSTART=1`.
The listener is guarded by a process lock to avoid duplicate Telegram
long-pollers.

## 3. Startup with the operating system

On Linux with systemd user services, install the provided user service:

```sh
./install.sh
systemctl --user status telegram-bridge
```

Interactive setup creates the private config, uses arrow keys and Enter to select
a detected coding-agent CLI, asks before registering MCP, securely prompts for
the bot token, then requests a numeric chat ID or offers automatic detection.
It validates the credentials before enabling the systemd user service. Canceling CLI registration
stops onboarding before credentials or service setup; run `telecode setup` again
to retry. For config-only changes use `telecode --configure-cli`.

To configure a coding-agent CLI, run `telecode setup` and choose a detected
client with the arrow keys, then press Enter. It detects installed OpenCode, Claude Code, Codex,
Gemini CLI, Cursor, Aider, Cline, Continue, Roo Code, and Amazon Q, then shows choices
available on this machine plus manual MCP. It makes a timestamped backup and
asks before changing config. Unsupported formats are left untouched with a
manual setup hint. Session switching is available only for a CLI with a
implemented supported session adapter; MCP tool support alone doesn't imply it.

`install_autostart.sh` is retained as a compatibility alias for
`install.sh --enable`; it no longer has a separate file-copy implementation.

The project intentionally does not offer a `curl | bash` one-liner: cloning
lets you inspect the source before executing it. To refresh installed files
from that checkout, run `./install.sh --update`; the private config is preserved.
For a clean, isolated local
installation smoke test, use `tests/test_installer.py`, which installs into a
temporary HOME and never starts a Telegram connection.

This starts the bot at user login. Enabling systemd lingering keeps user
services running without an interactive login where supported. Disable with:

```sh
systemctl --user disable --now telegram-bridge
```

Do not install both the service and an independent listener unless using this
project's lock guard; duplicate `getUpdates` pollers conflict at Telegram.

## 4. Other coding-agent CLIs

MCP-compatible clients can register `tg_mcp.py` using their local stdio-MCP
configuration. Session enumeration and prompt delivery are adapter-specific;
the OpenCode adapter is the current implementation. Claude Code support should
be configured through its MCP server settings, while any CLI without MCP needs
a dedicated adapter or hook. See `docs/ROADMAP.md` before assuming support.
