"""Command-line entry points and interactive TUI for TeleCode."""
import os
import pathlib
import subprocess
import sys

import telegram_bridge as tg
from . import ui
from .listener import cmd_listen as run_listener

USAGE = f"""{ui.accent('TeleCode')} — {ui.dim('Telegram bridge for coding agents')}

{ui.bold('Usage:')} telecode <command> [arguments]

{ui.bold('Commands:')}
  {ui.accent('menu')}                      Open the interactive command menu
  {ui.accent('setup')} [--web|--cli]       Open guided setup wizard (browser or terminal)
  {ui.accent('status')}                    Show bot, listener, session & unread inbox state
  {ui.accent('agent')} [NAME]              Show or switch active coding agent (e.g. hermes)
  {ui.accent('listen')}                    Start listener daemon in foreground
  {ui.accent('read')}                      Print unread Telegram messages and advance cursor
  {ui.accent('wait')} [SECONDS]            Wait for incoming message (default: 120s)
  {ui.accent('send')} [TEXT | PATH]        Send a message or file to Telegram owner chat
  {ui.accent('sendfile')} PATH [CAPTION]   Send a document/file to owner chat
  {ui.accent('get-id')}                    Detect or verify your numeric Telegram chat ID

{ui.bold('Options & Setup Flags:')}
  {ui.accent('--init')}                    Initialize environment and guided installer
  {ui.accent('--enable')}                  Enable per-user systemd/LaunchAgent startup
  {ui.accent('--configure-cli')}           Configure MCP client for installed agents
  {ui.accent('-h, --help')}                Show this help message and exit

Run 'telecode setup' to open the interactive setup menu.
"""


def _parse_wait_seconds(args):
    """Return the optional wait duration, rejecting ambiguous or unsafe values."""
    import re
    if len(args) > 1:
        raise ValueError("wait accepts at most one duration")
    if not args:
        return 120
    value = args[0]
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError("duration must be a whole number of seconds")
    seconds = int(value)
    if not 1 <= seconds <= 86400:
        raise ValueError("duration must be between 1 and 86400 seconds")
    return seconds


def cmd_read():
    recs = tg._unread()
    if not recs:
        if sys.stdout.isatty():
            print(ui.dim("No unread messages."))
        return 0
    if sys.stdout.isatty() or ui.supports_color():
        card_rows = []
        for r in recs:
            for l in ui.format_message(r):
                card_rows.append(l)
        print()
        for line in ui.box(f"TeleCode Inbox ({len(recs)} unread)", card_rows):
            print(line)
        print()
    else:
        for r in recs:
            for line in ui.format_message(r):
                print(line)
    tg._advance(recs)
    return 0


def cmd_wait():
    import time
    try:
        seconds = _parse_wait_seconds(sys.argv[2:])
    except ValueError as exc:
        print(f"telecode wait: {exc}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    if sys.stdout.isatty():
        print(ui.dim(f"Waiting for incoming messages (timeout: {seconds}s, Ctrl-C to cancel)..."))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        recs = tg._unread()
        if recs:
            if sys.stdout.isatty() or ui.supports_color():
                card_rows = []
                for r in recs:
                    for l in ui.format_message(r):
                        card_rows.append(l)
                print()
                for line in ui.box(f"TeleCode Inbox ({len(recs)} received)", card_rows):
                    print(line)
                print()
            else:
                for r in recs:
                    for line in ui.format_message(r):
                        print(line)
            tg._advance(recs)
            return 0
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    print(f"TIMEOUT: no message within {seconds}s")
    return 3


def cmd_send(args=None):
    try:
        cfg = tg.load_env()
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        print(ui.error_line(f"Configuration error: {exc}"), file=sys.stderr)
        return 1

    if args is None:
        args = sys.argv[2:]

    # Support --file PATH [CAPTION] or -f PATH [CAPTION]
    if args and args[0] in ("--file", "-f"):
        if len(args) < 2:
            print("usage: telecode send --file PATH [CAPTION]", file=sys.stderr)
            return 2
        path = pathlib.Path(os.path.expanduser(args[1]))
        caption = " ".join(args[2:]).strip() if len(args) > 2 else ""
        if not path.is_file() or path.is_symlink():
            print(ui.error_line(f"no such file: {path}"), file=sys.stderr)
            return 2
        mid = tg.send_file(cfg, path, caption)
        print(ui.ok_line(f"sent file ok (message_id={mid})"))
        return 0

    # If first argument is an existing file, treat as file upload
    if args:
        candidate = pathlib.Path(os.path.expanduser(args[0]))
        if candidate.is_file() and not candidate.is_symlink():
            caption = " ".join(args[1:]).strip() if len(args) > 1 else ""
            mid = tg.send_file(cfg, candidate, caption)
            print(ui.ok_line(f"sent file ok (message_id={mid})"))
            return 0
        text = " ".join(args).strip()
    else:
        text = ""

    # Non-interactive stdin pipe
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read().strip()

    # Interactive prompt
    if not text and sys.stdin.isatty():
        try:
            user_input = input("Message text or file path (or Ctrl-C to cancel): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
        if not user_input:
            print("usage: telecode send [TEXT | PATH]   (or pipe text via stdin)", file=sys.stderr)
            return 2
        candidate = pathlib.Path(os.path.expanduser(user_input))
        if candidate.is_file() and not candidate.is_symlink():
            try:
                caption = input("Caption (optional, Enter to skip): ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 130
            mid = tg.send_file(cfg, candidate, caption)
            print(ui.ok_line(f"sent file ok (message_id={mid})"))
            return 0
        text = user_input

    if not text:
        print("usage: telecode send [TEXT | PATH]   (or pipe text via stdin)", file=sys.stderr)
        return 2

    mid = tg.send_text(cfg, text)
    print(ui.ok_line(f"sent ok (message_id={mid})"))
    return 0


def cmd_sendfile(args=None):
    try:
        cfg = tg.load_env()
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        print(ui.error_line(f"Configuration error: {exc}"), file=sys.stderr)
        return 1
    if args is None:
        args = sys.argv[2:]
    if len(args) < 1:
        print("usage: telecode sendfile PATH [CAPTION]", file=sys.stderr)
        return 2
    path = pathlib.Path(os.path.expanduser(args[0]))
    caption = " ".join(args[1:]).strip() if len(args) > 1 else ""
    if not path.is_file() or path.is_symlink():
        print(ui.error_line(f"no such file: {path}"), file=sys.stderr)
        return 2
    mid = tg.send_file(cfg, path, caption)
    print(ui.ok_line(f"sent file ok (message_id={mid})"))
    return 0


def cmd_status():
    try:
        cfg = tg.load_env()
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        print(ui.error_line(f"Configuration error: {exc}"), file=sys.stderr)
        print(ui.dim("Run 'telecode setup' to configure Telegram credentials."), file=sys.stderr)
        return 1
    try:
        me = tg.api(cfg["TG_BOT_TOKEN"], "getMe", timeout=15)
    except Exception as exc:
        print(ui.error_line(f"Telegram API unreachable: {exc}"), file=sys.stderr)
        return 1
    bot = me.get("result") or {}
    alive_dot = ui.status_dot(False)
    alive_text = ui.red("down")
    if tg.PID.exists():
        pid = tg.PID.read_text().strip()
        try:
            os.kill(int(pid), 0)
            alive_dot = ui.status_dot(True)
            alive_text = ui.green(f"up (pid {pid})")
        except Exception:
            alive_dot = ui.status_dot(None)
            alive_text = ui.yellow(f"stale pid {pid}")
    sid, how = tg.resolve_session(cfg)
    active_agent = tg._agent_name(cfg)
    rows = [
        ("Agent", f"{tg.agent_label(active_agent)} ({active_agent})"),
        ("Bot", f"@{bot.get('username')} (id {bot.get('id')})"),
        ("Owner chat", ui.mask_value(cfg.get("TG_CHAT_ID", ""))),
        ("Listener", f"{alive_dot} {alive_text}"),
        ("Session", f"{sid or '(none)'} [{how}]"),
        ("Delivery", f"{cfg.get('TG_DELIVERY') or 'steer'} "
                     f"(mode {cfg.get('OPENCODE_SESSION_MODE') or 'auto'})"),
        ("Unread", str(len(tg._unread()))),
    ]
    if tg.STATE.exists():
        rows.append(("Last target", tg.STATE.read_text().strip()))
    if hasattr(tg, "LOG") and tg.LOG.exists():
        rows.append(("Log file", str(tg.LOG)))

    if sys.stdout.isatty() or ui.supports_color():
        print()
        for line in ui.key_value_card("TeleCode Status", rows):
            print(line)
        print()
    else:
        width = max(ui.visible_width(label) for label, _ in rows)
        for label, value in rows:
            print(f"{ui.dim(ui.pad(label, width))}  {value}")
    return 0


def cmd_agent(args=None):
    """View supported coding agents or switch the active agent."""
    import shutil
    if args is None:
        args = sys.argv[2:]
    args = list(args)
    try:
        cfg = tg.load_env()
    except (FileNotFoundError, PermissionError, ValueError):
        cfg = {}

    binaries = {
        "opencode": ["opencode", str(pathlib.Path.home() / ".opencode/bin/opencode")],
        "claude-code": ["claude"],
        "codex": ["codex"],
        "cursor": ["agent"],
        "hermes": ["hermes"],
    }

    if not args:
        active = tg.normalize_agent(tg._agent_name(cfg)) or "opencode"
        sid, _ = tg.resolve_session(cfg)
        card_rows = []
        for aid, label in tg.AGENT_LABELS.items():
            is_active = (aid == active)
            detected = any(shutil.which(b) for b in binaries.get(aid, [aid]))
            status_parts = []
            if is_active:
                status_parts.append(ui.green("● active"))
            if detected:
                status_parts.append(ui.dim("installed"))
            else:
                status_parts.append(ui.dim("not detected"))
            card_rows.append((label, f"{' · '.join(status_parts)} ({aid})"))

        if sid:
            card_rows.append(("Active session", f"{sid}"))

        if sys.stdout.isatty() or ui.supports_color():
            print()
            for line in ui.key_value_card("Coding Agents", card_rows):
                print(line)
            print()
            print(ui.dim("Switch agent: telecode agent <name> (e.g. telecode agent hermes)"))
            print()
        else:
            width = max(ui.visible_width(label) for label, _ in card_rows)
            for label, value in card_rows:
                print(f"{ui.dim(ui.pad(label, width))}  {value}")
        return 0

    target = args[0].strip()
    canonical = tg.normalize_agent(target)
    if not canonical:
        supported = ", ".join(tg.AGENT_LABELS)
        print(ui.error_line(f"Unknown agent '{target}'. Supported: {supported}"), file=sys.stderr)
        return 2

    try:
        active_session = tg.switch_active_agent(cfg, canonical)
    except Exception as exc:
        print(ui.error_line(f"Failed to switch agent: {exc}"), file=sys.stderr)
        return 1

    label = tg.agent_label(canonical)
    if active_session:
        sid = active_session.get("id") or ""
        stitle = tg.session_title(active_session)
        print(ui.ok_line(f"Switched active agent to {ui.bold(label)}."))
        print(ui.dim(f"Session: {stitle} [{sid}]"))
    else:
        print(ui.ok_line(f"Switched active agent to {ui.bold(label)}."))
        print(ui.dim(f"No existing sessions found for {label}. Start one in Telegram or via the agent CLI."))
    return 0


def _save_env_var(key: str, value: str) -> None:
    tg.save_env_var(key, value)


def run_web_setup() -> int:
    app_dir = pathlib.Path(__file__).resolve().parent.parent
    web_script = app_dir / "setup_web.py"
    if not web_script.is_file():
        print(ui.error_line("Browser setup script not found; reinstall TeleCode"), file=sys.stderr)
        return 2
    env = os.environ.copy()
    env["TELEGRAM_BRIDGE_APP_DIR"] = str(app_dir)
    env["TELEGRAM_BRIDGE_HOME"] = str(tg.ENV.parent)

    web_card = [
        ("Wizard mode", "Browser-based credentials & agent wizard"),
        ("Access", "Loopback only (127.0.0.1)"),
        ("Session timeout", "15 minutes"),
        ("SSH forwarding", "ssh -L <port>:127.0.0.1:<port> <remote-host>"),
    ]
    print()
    for line in ui.key_value_card("TeleCode Browser Setup Wizard", web_card):
        print(line)
    print()
    print(ui.ok_line("Starting browser setup wizard..."))
    return subprocess.call([sys.executable, str(web_script)], env=env)


def run_cli_setup() -> int:
    import re
    app_dir = pathlib.Path(__file__).resolve().parent.parent
    cli_script = app_dir / "setup_cli.py"
    if not cli_script.is_file():
        print(ui.error_line("Terminal setup script not found; reinstall TeleCode"), file=sys.stderr)
        return 2

    print()
    print(ui.bold(ui.accent("TeleCode Terminal Setup Wizard")))
    print(ui.dim("Configure your coding agent, Telegram credentials, and background service."))
    print()

    # Step 1: Agent CLI configuration
    print(ui.bold("Step 1 of 4: Coding-Agent CLI Configuration"))
    print(ui.dim("Configure MCP integration so your agent can communicate with TeleCode."))
    print()

    env = os.environ.copy()
    env["TELEGRAM_BRIDGE_APP_DIR"] = str(app_dir)
    rc = subprocess.call([sys.executable, str(cli_script)], env=env)
    if rc != 0:
        return rc

    try:
        cfg = tg.load_env()
    except Exception:
        cfg = {}

    has_token = bool(cfg.get("TG_BOT_TOKEN") and ":" in cfg["TG_BOT_TOKEN"])
    has_chat = bool(cfg.get("TG_CHAT_ID") and cfg["TG_CHAT_ID"].lstrip("-").isdigit())

    # Step 2: Telegram Bot Token configuration
    print()
    print(ui.bold("Step 2 of 4: Telegram Bot Token Configuration"))
    print(ui.dim("Obtain a bot token from @BotFather on Telegram (e.g. 123456789:ABCdef...)."))
    print()

    if has_token:
        curr_masked = ui.mask_token(cfg["TG_BOT_TOKEN"])
        print(ui.ok_line(f"Bot token already configured: {curr_masked}"))
        try:
            change = input(f"Keep this token? [{ui.bold('Y')}/{ui.dim('n')}]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
        if change in ("n", "no"):
            has_token = False

    if not has_token:
        for attempt in range(1, 4):
            try:
                import getpass
                tok = getpass.getpass("Telegram bot token (from @BotFather): ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 130
            if re.match(r"^\d{5,}:[A-Za-z0-9_-]{20,}$", tok):
                _save_env_var("TG_BOT_TOKEN", tok)
                cfg["TG_BOT_TOKEN"] = tok
                print(ui.ok_line(f"Bot token saved: {ui.mask_token(tok)}"))
                has_token = True
                break
            print(ui.warn_line(f"Invalid token format (expected 12345:ABC...). Attempt {attempt} of 3."))
        if not has_token:
            print(ui.error_line("Bot token was not saved."), file=sys.stderr)
            return 2

    # Step 3: Owner Chat ID configuration
    print()
    print(ui.bold("Step 3 of 4: Owner Chat ID Configuration"))
    print(ui.dim("Your numeric Telegram chat ID ensures only you can access the bot."))
    print()

    if has_chat:
        curr_chat = ui.mask_value(cfg["TG_CHAT_ID"])
        print(ui.ok_line(f"Owner chat ID already configured: {curr_chat}"))
        try:
            change = input(f"Keep this chat ID? [{ui.bold('Y')}/{ui.dim('n')}]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
        if change in ("n", "no"):
            has_chat = False

    if not has_chat:
        for attempt in range(1, 4):
            try:
                cid = input("Numeric owner chat ID (or 'a' for auto-detection): ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 130
            if cid.lower() == "a":
                helper = app_dir / "get_telegram_id.py"
                env_cid = os.environ.copy()
                env_cid["TELEGRAM_BRIDGE_HOME"] = str(tg.ENV.parent)
                subprocess.call([sys.executable, str(helper), "--configure"], env=env_cid)
                try:
                    cfg = tg.load_env()
                    if cfg.get("TG_CHAT_ID"):
                        has_chat = True
                        break
                except Exception:
                    pass
                has_chat = True
                break
            if re.match(r"^-?\d+$", cid):
                _save_env_var("TG_CHAT_ID", cid)
                cfg["TG_CHAT_ID"] = cid
                print(ui.ok_line(f"Chat ID saved: {cid}"))
                has_chat = True
                break
            print(ui.warn_line(f"Enter a numeric chat ID or 'a'. Attempt {attempt} of 3."))
        if not has_chat:
            print(ui.error_line("Chat ID was not saved."), file=sys.stderr)
            return 2

    # Step 4: System service startup
    print()
    print(ui.bold("Step 4 of 4: System Service Startup"))
    print(ui.dim("Enable background listener service to run automatically on system boot / login."))
    print()

    service_state = "Not enabled (run 'telecode listen' to start manually)"
    try:
        start_svc = input(f"Enable background service now? [{ui.bold('y')}/{ui.dim('N')}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 130

    if start_svc in ("y", "yes"):
        install_script = app_dir / "install.sh"
        if install_script.is_file():
            svc_rc = subprocess.call(["bash", str(install_script), "--enable"])
            if svc_rc == 0:
                service_state = ui.green("Enabled and running")
            else:
                service_state = ui.yellow("Service setup incomplete (check systemd/supervisor)")
        else:
            service_state = ui.dim("installer not found")

    # Present clean summary card upon completion
    try:
        final_cfg = tg.load_env()
    except Exception:
        final_cfg = cfg

    configured_agent = tg._agent_name(final_cfg) if hasattr(tg, "_agent_name") else final_cfg.get("TELECODE_AGENT", "opencode")
    tok_val = final_cfg.get("TG_BOT_TOKEN", "")
    chat_val = final_cfg.get("TG_CHAT_ID", "")

    summary_items = [
        ("Configured agent", ui.accent(configured_agent)),
        ("Bot token", ui.mask_token(tok_val) if tok_val else "(none)"),
        ("Owner chat ID", ui.mask_value(chat_val) if chat_val else "(none)"),
        ("Background service", service_state),
        ("Verify status", "telecode status"),
        ("Test message", 'telecode send "Hello from TeleCode"'),
    ]

    print()
    for line in ui.key_value_card("TeleCode Setup Summary", summary_items):
        print(line)
    print()
    print(ui.ok_line("Setup complete! Your coding agent and Telegram bridge are ready."))
    return 0


def cmd_setup(args=None) -> int:
    args = args or []
    if any(a in ("--web", "--browser") for a in args):
        return run_web_setup()
    if "--cli" in args:
        return run_cli_setup()
    if args:
        print("usage: telecode setup [--web|--cli]", file=sys.stderr)
        return 2

    options = [
        ("Browser wizard (recommended)", "configure credentials and agent via browser", "web"),
        ("Terminal wizard", "configure in this terminal", "cli"),
        ("Back to main menu", "", "back"),
    ]
    width = max(ui.visible_width(label) for label, _, _ in options)
    setup_rows = []
    for index, (label, hint, _) in enumerate(options, 1):
        suffix = f"  {ui.dim(hint)}" if hint else ""
        setup_rows.append(f"  {ui.accent(str(index) + '.')} {ui.bold(ui.pad(label, width))}{suffix}")

    print()
    for line in ui.box("TeleCode Setup Wizard", setup_rows):
        print(line)
    print()
    print(ui.dim("1-2 select · 3 or q back · Ctrl-C cancel"))
    while True:
        try:
            answer = input("TeleCode (setup) › ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
        if answer in ("q", "quit", "back", "3"):
            return 0
        if answer in ("1", "b", "browser", "web"):
            return run_web_setup()
        if answer in ("2", "t", "terminal", "cli"):
            return run_cli_setup()
        print(ui.error_line("Choose 1-2 or enter 'q' to go back."), file=sys.stderr)


def cmd_menu():
    """Show the organized command menu used by `telecode` on a terminal."""
    options = [
        ("Setup wizard", "configure an agent and Telegram credentials", "setup"),
        ("Show status", "bot, listener, session and unread messages", "status"),
        ("Start listener", "run in this terminal", "listen"),
        ("Read messages", "show unread Telegram messages", "read"),
        ("Wait for message", "wait up to 120 seconds", "wait"),
        ("Send a message", "send text to your configured Telegram chat", "send"),
        ("Find chat ID", "detect your private chat using your own bot", "get-id"),
        ("Help / commands", "show command reference", "help"),
        ("Switch agent", "view or switch active coding agent", "agent"),
        ("Exit", "", "exit"),
    ]
    width = max(ui.visible_width(label) for label, _, _ in options)
    menu_rows = []
    for index, (label, hint, _) in enumerate(options, 1):
        suffix = f"  {ui.dim(hint)}" if hint else ""
        menu_rows.append(f"  {ui.accent(str(index) + '.')} {ui.bold(ui.pad(label, width))}{suffix}")

    print()
    for line in ui.box("TeleCode — Telegram bridge for coding agents", menu_rows):
        print(line)
    print()
    print(ui.dim("1-9 select · 10 or q exit · Ctrl-C cancel"))
    while True:
        try:
            answer = input("TeleCode › ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
        if answer in ("q", "quit", "exit", "10", "9") and ("9" not in answer or len(options) < 10):
            return 0
        if answer in ("q", "quit", "exit", "10"):
            return 0
        selected = next((command for index, (_, _, command) in enumerate(options, 1)
                         if answer in (str(index), command)), None)
        if selected is None:
            print(ui.error_line("Choose 1-10 or enter a command name."), file=sys.stderr)
            continue
        if selected == "exit":
            return 0
        if selected == "setup":
            return cmd_setup()
        if selected == "status":
            return cmd_status()
        if selected == "listen":
            return run_listener()
        if selected == "read":
            return cmd_read()
        if selected == "wait":
            print(f"Usage: telecode wait [SECONDS]  {ui.dim('(wait up to SECONDS, default 120s)')}")
            return 0
        if selected == "send":
            return cmd_send()
        if selected == "agent":
            return cmd_agent([])
        if selected == "get-id":
            helper = pathlib.Path(__file__).resolve().parent.parent / "get_telegram_id.py"
            return subprocess.call([sys.executable, str(helper)])
        if selected == "help":
            print(USAGE)
            return 0


def cmd_menu_once():
    """Compatibility entry point for tests and older internal callers."""
    return cmd_menu()


def cmd_install():
    """Install the current checkout as a user-level systemd service."""
    source = pathlib.Path(__file__).resolve().parent.parent
    script = source / "install.sh"
    if not script.is_file():
        print("installer not found; use the release install.sh", file=sys.stderr)
        return 2
    return subprocess.call(["bash", str(script), "--enable"])


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(USAGE)
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "get-id":
        helper = pathlib.Path(__file__).resolve().parent.parent / "get_telegram_id.py"
        if not helper.is_file():
            print("chat ID helper is not installed; reinstall TeleCode", file=sys.stderr)
            return 2
        return subprocess.call([sys.executable, str(helper)])
    if len(sys.argv) > 1 and sys.argv[1] == "--init":
        return subprocess.call(["bash", str(pathlib.Path(__file__).resolve().parent.parent / "install.sh")])
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        return cmd_setup(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] in ("--enable", "--configure-cli"):
        args = ["bash", str(pathlib.Path(__file__).resolve().parent.parent / "install.sh"), sys.argv[1]]
        return subprocess.call(args)
    cmds = {
        "listen": run_listener, "read": cmd_read, "wait": cmd_wait,
        "send": cmd_send, "sendfile": cmd_sendfile, "status": cmd_status,
        "menu": cmd_menu, "setup": cmd_setup, "agent": cmd_agent,
    }
    if len(sys.argv) < 2:
        if sys.stdin.isatty() and sys.stdout.isatty():
            try:
                return cmd_menu()
            except KeyboardInterrupt:
                print("\nStopped.", file=sys.stderr)
                return 130
        print(USAGE, file=sys.stderr)
        return 2
    if sys.argv[1] not in cmds:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        return cmds[sys.argv[1]]() or 0
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
