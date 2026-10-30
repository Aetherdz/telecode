# Installation and startup

## Supported platforms

The guided installer requires Python 3.11+ and Bash. Login startup uses systemd
user services on Linux, a LaunchAgent on macOS, and a per-user Scheduled Task on
Windows. In headless environments where the user's service-manager session is
unavailable, setup warns and prints the foreground command (`telecode listen`).

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

The guided installer enables the operating system's per-user startup service.
On Linux, inspect it with:

```sh
./install.sh
systemctl --user status telegram-bridge
```

On macOS, the installer writes `~/Library/LaunchAgents/org.telecode.telegram-bridge.plist`;
on Windows, it registers the `TeleCode Telegram Bridge` Task Scheduler task. Use
`./install.sh --uninstall` to disable/remove the startup service while preserving
the application and private configuration. On headless systems without the
required user session, keep the listener running in the foreground (or under your
own supervisor):

```sh
telecode listen
```

Interactive setup creates the private config, shows an aligned menu where arrow
keys and Enter (or a number) select a detected coding-agent CLI, asks before
registering MCP, securely prompts for the bot token, then requests a numeric chat
ID or offers automatic detection. It validates credentials before enabling the
platform service. If the service manager is unavailable, setup finishes without
enabling a service and prints `telecode listen`. Canceling CLI
registration stops onboarding before credentials or service setup; run
`telecode setup` again to retry. For config-only changes use
`telecode --configure-cli`.

To configure a coding-agent CLI, run `telecode setup` and choose a detected
client with the arrow keys, then press Enter. It detects installed OpenCode, Claude Code, Codex,
Gemini CLI, Cursor, Aider, Cline, Continue, Roo Code, and Amazon Q, then shows choices
available on this machine plus manual MCP. It makes a timestamped backup and
asks before changing config. Unsupported formats are left untouched with a
manual setup hint. Session switching is available only for a CLI with a
implemented supported session adapter; MCP tool support alone doesn't imply it.

`install_autostart.sh` is retained as a compatibility alias for
`install.sh --enable`; it no longer has a separate file-copy implementation.

The website provides an optional `curl | bash` bootstrap that downloads the
installer from this public repository, fetches the source into a private cache,
and starts guided setup. Review `install.sh` before running it. Alternatively,
clone and inspect the project, then run `./install.sh` yourself. To refresh
installed files from a checkout, run `./install.sh --update`; private config is
preserved.
For a clean, isolated local
installation smoke test, use `tests/test_installer.py`, which installs into a
temporary HOME and never starts a Telegram connection.

This starts the bot at user login. On Linux, enabling systemd lingering keeps
user services running without an interactive login where supported. Disable on
Linux with:

```sh
./install.sh --uninstall
```

Do not install both the service and an independent listener unless using this
project's lock guard; duplicate `getUpdates` pollers conflict at Telegram.

## 4. Other coding-agent CLIs

MCP-compatible clients can register `tg_mcp.py` using their local stdio-MCP
configuration. Session enumeration and prompt delivery are adapter-specific;
the OpenCode adapter is the current implementation. Claude Code support should
be configured through its MCP server settings, while any CLI without MCP needs
a dedicated adapter or hook. See `docs/ROADMAP.md` before assuming support.
