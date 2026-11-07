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

On POSIX systems TeleCode writes credential files with mode `0600`. The
installer also applies a current-user-only ACL to its generated Windows
credential file. In contrast, the Python atomic config writers do not set
Windows ACLs: those files rely on the user profile directory's default
permissions, which are **not equivalent to POSIX `0600`**. Review your Windows
account/profile ACLs if stronger isolation is required; explicit ACL management
by these writers is a possible follow-up.

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

Interactive setup offers Browser (recommended) or Terminal on a TTY. The browser
wizard binds only to `127.0.0.1`, uses a one-time local URL, and expires after
15 minutes. From SSH, forward its displayed port with the suggested `ssh -L`
command. Use `./install.sh --web` or `telecode setup --web` to open it directly;
`--browser-setup` remains an alias. Use `./install.sh --cli` or
`telecode setup --cli` for the unchanged terminal flow.

The interactive terminal setup (`telecode setup --cli` or `telecode setup`) guides you through four sequential steps:

1. **Step 1 of 4: Coding-Agent CLI Configuration:** Detects installed coding agents (OpenCode, Claude Code, Hermes Agent, Codex CLI, Cursor, etc.), displays an arrow-driven selector, creates timestamped backups of existing config files, and registers the local stdio MCP server.
2. **Step 2 of 4: Telegram Bot Token Configuration:** Prompts securely for your bot token from [@BotFather](https://t.me/BotFather) with hidden password-style input and format validation. Existing tokens can be kept or replaced.
3. **Step 3 of 4: Owner Chat ID Configuration:** Prompts for your numeric Telegram chat ID, or type `a` for automatic detection via `get_telegram_id.py --configure` (which captures your ID when you message `/start` to your bot).
4. **Step 4 of 4: System Service Startup:** Offers to enable the background service immediately using `install.sh --enable` (systemd user unit, LaunchAgent, or Scheduled Task).

Upon completion, a clean summary card confirms the configured agent, credentials, service status, and verification commands (`telecode status` and `telecode send`). If the service manager is unavailable, setup finishes without enabling a service and prints `telecode listen`. Canceling CLI registration stops onboarding before credentials or service setup; run `telecode setup` again to retry. For config-only changes use `telecode --configure-cli`.

To configure a coding-agent CLI directly, run `telecode setup` and choose a detected client with the arrow keys, then press Enter. It detects installed OpenCode, Claude Code, Hermes Agent, Codex, Gemini CLI, Cursor, Aider, Cline, Continue, Roo Code, and Amazon Q, then shows choices available on this machine plus manual MCP. It makes a timestamped backup and asks before changing config. Unsupported formats are left untouched with a manual setup hint. Session switching is available for CLIs with an implemented session adapter (OpenCode, Claude Code, Hermes Agent, Codex, and Cursor); MCP tool support alone doesn't imply it.

`install_autostart.sh` is retained as a compatibility alias for
`install.sh --enable`; it no longer has a separate file-copy implementation.

The website provides an optional `curl | bash` bootstrap that downloads the
installer from this public repository, fetches the source into a private cache,
and starts guided setup. Review `install.sh` before running it. Alternatively,
clone and inspect the project, then run `./install.sh` yourself. To refresh
installed files from a checkout, run `./install.sh --update`; private config is
preserved.

See the [terminal installer preview](screenshots/telecode-cli.svg) and the
[browser wizard step wireframe](screenshots/telecode-setup-steps.svg). The
wireframe is explicitly a design preview, not a screenshot of runtime behavior.
Runtime browser-step screenshots are not included yet; do not treat the wireframe
as captured output.
Installer options include `--verbose`, `--quiet`, `--yes`, `--dry-run`, `--update`,
`--help`, `--version`, `--curl-bootstrap`, `--web`, and `--cli`. Dry-run prints the
plan without writing files; a repeated install reports files already up to date.
Output from setup steps is captured and only shown on failure, with a short tail
and remediation hint. `NO_COLOR` disables ANSI color; non-TTY output is plain text.

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
OpenCode, Claude Code, and Hermes Agent adapters are available out of the box, with
experimental support for Codex CLI and Cursor. Any CLI without MCP needs
a dedicated adapter or hook. See `docs/CLI.md` for client details.
