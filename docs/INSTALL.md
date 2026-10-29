# Installation and startup

## 1. Prepare credentials

Create a bot with BotFather, then create a private chat with it. Copy this
project's `.env.example` to the runtime directory as `telegram.env`, fill in
the bot token and numeric owner chat ID, and restrict permissions:

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
./install.sh --bootstrap
telecode setup
systemctl --user status telegram-bridge
```

Interactive setup creates the private config, asks before registering MCP with
the selected CLI, collects the bot token, waits for `/start` to save the private
owner chat ID, and enables the systemd user service. Canceling CLI registration
stops onboarding before credentials or service setup; run `telecode setup` again
to retry. For config-only changes use `telecode --configure-cli`.

To configure a coding-agent CLI, run the installer and choose **Configure a
detected coding-agent CLI**. It detects installed OpenCode, Claude Code, Codex,
Gemini CLI, Cursor, Aider, Cline, Continue, Roo Code, and Amazon Q, then shows choices
available on this machine plus manual MCP. It makes a timestamped backup and
asks before changing config. Unsupported formats are left untouched with a
manual setup hint. Session switching is available only for a CLI with a
implemented supported session adapter; MCP tool support alone doesn't imply it.

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
