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
  {ui.accent('setup')} [--web|--cli]       Open guided setup wizard (browser or terminal)
  {ui.accent('status')}                    Show bot, listener, session & unread inbox state
  {ui.accent('listen')}                    Start listener daemon in foreground
  {ui.accent('read')}                      Print unread Telegram messages and advance cursor
  {ui.accent('wait')} [SECONDS]            Wait for incoming message (default: 120s)
  {ui.accent('send')} TEXT                 Send a message to configured Telegram owner chat
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
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        recs = tg._unread()
        if recs:
            for r in recs:
                for line in ui.format_message(r):
                    print(line)
            tg._advance(recs)
            return 0
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    print(f"TIMEOUT: no message within {seconds}s")
    return 3


def cmd_send():
    try:
        cfg = tg.load_env()
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        print(ui.error_line(f"Configuration error: {exc}"), file=sys.stderr)
        return 1
    text = " ".join(sys.argv[2:]).strip() if len(sys.argv) > 2 else sys.stdin.read().strip()
    if not text:
        print("usage: telecode send TEXT   (or pipe text via stdin)", file=sys.stderr)
        return 2
    mid = tg.send_text(cfg, text)
    print(ui.ok_line(f"sent ok (message_id={mid})"))
    return 0


def cmd_sendfile():
    try:
        cfg = tg.load_env()
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        print(ui.error_line(f"Configuration error: {exc}"), file=sys.stderr)
        return 1
    if len(sys.argv) < 3:
        print("usage: telecode sendfile PATH [CAPTION]", file=sys.stderr)
        return 2
    path = pathlib.Path(os.path.expanduser(sys.argv[2]))
    caption = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
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
    rows = [
        ("bot", f"@{bot.get('username')} (id {bot.get('id')})"),
        ("owner chat", ui.mask_value(cfg.get("TG_CHAT_ID", ""))),
        ("listener", f"{alive_dot} {alive_text}"),
        ("session", f"{sid or '(none)'} [{how}]"),
        ("delivery", f"{cfg.get('TG_DELIVERY') or 'steer'} "
                     f"(mode {cfg.get('OPENCODE_SESSION_MODE') or 'auto'})"),
        ("unread", str(len(tg._unread()))),
    ]
    if tg.STATE.exists():
        rows.append(("last delivered", tg.STATE.read_text().strip()))
    if hasattr(tg, "LOG") and tg.LOG.exists():
        rows.append(("log file", str(tg.LOG)))

    if ui.supports_color():
        print()
        for line in ui.key_value_card("TeleCode Status", rows):
            print(line)
        print()
    else:
        width = max(ui.visible_width(label) for label, _ in rows)
        for label, value in rows:
            print(f"{ui.dim(ui.pad(label, width))}  {value}")
    return 0


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
        ("Exit", "", "exit"),
    ]
    width = max(ui.visible_width(label) for label, _, _ in options)
    menu_rows = []
    for index, (label, hint, _) in enumerate(options, 1):
        suffix = f"  {ui.dim(hint)}" if hint else ""
        menu_rows.append(f"  {ui.accent(str(index) + '.')} {ui.pad(label, width)}{suffix}")

    print()
    for line in ui.box("TeleCode — Telegram bridge for coding agents", menu_rows):
        print(line)
    print()
    print(ui.dim("1-8 select · 9 or q exit · Ctrl-C cancel"))
    while True:
        try:
            answer = input("TeleCode › ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
        if answer in ("q", "quit", "exit", "9"):
            return 0
        selected = next((command for index, (_, _, command) in enumerate(options, 1)
                         if answer in (str(index), command)), None)
        if selected is None:
            print(ui.error_line("Choose 1-9 or enter a command name."), file=sys.stderr)
            continue
        if selected == "exit":
            return 0
        if selected == "setup":
            installer = pathlib.Path(__file__).resolve().parent.parent / "install.sh"
            return subprocess.call(["bash", str(installer), "--setup"])
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
            print(f"Usage: telecode send TEXT  {ui.dim('(send text to configured Telegram chat)')}")
            return 0
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
        installer = str(pathlib.Path(__file__).resolve().parent.parent / "install.sh")
        if len(sys.argv) > 2 and sys.argv[2] in ("--web", "--browser"):
            return subprocess.call(["bash", installer, "--web"])
        if len(sys.argv) > 2 and sys.argv[2] == "--cli":
            return subprocess.call(["bash", installer, "--cli"])
        if len(sys.argv) > 2:
            print("usage: telecode setup [--web|--cli]", file=sys.stderr)
            return 2
        return subprocess.call(["bash", installer])
    if len(sys.argv) > 1 and sys.argv[1] in ("--enable", "--configure-cli"):
        args = ["bash", str(pathlib.Path(__file__).resolve().parent.parent / "install.sh"), sys.argv[1]]
        return subprocess.call(args)
    cmds = {
        "listen": run_listener, "read": cmd_read, "wait": cmd_wait,
        "send": cmd_send, "sendfile": cmd_sendfile, "status": cmd_status,
        "menu": cmd_menu,
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
