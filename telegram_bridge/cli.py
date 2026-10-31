"""Command-line entry points for the bridge."""
import os
import pathlib
import subprocess
import sys

import telegram_bridge as tg
from . import ui

USAGE = ("usage: telecode {setup|listen|read|wait [SECONDS]|send TEXT|"
         "sendfile PATH [CAPTION]|status|get-id|--init|--enable|--configure-cli|--help}\n"
         "Run 'telecode setup' to open the interactive setup menu.")


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
    for r in recs:
        line = f"[{r['iso']}] {r['text']}"
        if r.get("file"):
            line += f"\n    FILE: {r['file']}"
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
                line = f"[{r['iso']}] {r['text']}"
                if r.get("file"):
                    line += f"\n    FILE: {r['file']}"
                print(line)
            tg._advance(recs)
            return 0
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    print(f"TIMEOUT: no message within {seconds}s")
    return 3


def cmd_send():
    cfg = tg.load_env()
    text = " ".join(sys.argv[2:]).strip() if len(sys.argv) > 2 else sys.stdin.read().strip()
    if not text:
        print("usage: tg_bridge.py send <text>   (or pipe text via stdin)", file=sys.stderr)
        return 2
    mid = tg.send_text(cfg, text)
    print(f"sent ok (message_id={mid})")
    return 0


def cmd_sendfile():
    cfg = tg.load_env()
    if len(sys.argv) < 3:
        print("usage: tg_bridge.py sendfile <path> [caption]", file=sys.stderr)
        return 2
    path = pathlib.Path(os.path.expanduser(sys.argv[2]))
    caption = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
    if not path.is_file() or path.is_symlink():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    mid = tg.send_file(cfg, path, caption)
    print(f"sent file ok (message_id={mid})")
    return 0


def cmd_status():
    cfg = tg.load_env()
    try:
        me = tg.api(cfg["TG_BOT_TOKEN"], "getMe", timeout=15)
    except Exception as exc:
        print(ui.error_line(f"Telegram API unreachable: {exc}"), file=sys.stderr)
        return 1
    bot = me.get("result") or {}
    alive = "down"
    alive_tone = "red"
    if tg.PID.exists():
        pid = tg.PID.read_text().strip()
        try:
            os.kill(int(pid), 0)
            alive = f"up (pid {pid})"
            alive_tone = "green"
        except Exception:
            alive = f"stale pid {pid}"
            alive_tone = "yellow"
    sid, how = tg.resolve_session(cfg)
    rows = [
        ("bot", f"@{bot.get('username')} (id {bot.get('id')})"),
        ("owner chat", ui.mask_value(cfg.get("TG_CHAT_ID", ""))),
        ("listener", alive),
        ("session", f"{sid or '(none)'} [{how}]"),
        ("delivery", f"{cfg.get('TG_DELIVERY') or 'steer'} "
                     f"(mode {cfg.get('OPENCODE_SESSION_MODE') or 'auto'})"),
        ("unread", str(len(tg._unread()))),
    ]
    if tg.STATE.exists():
        rows.append(("last delivered", tg.STATE.read_text().strip()))
    width = max(ui.visible_width(label) for label, _ in rows)
    for label, value in rows:
        text = value
        if label == "listener":
            text = getattr(ui, alive_tone)(value)
        print(f"{ui.dim(ui.pad(label, width))}  {text}")
    return 0


def cmd_menu():
    """Small Setup/Exit menu used by `telecode` on a terminal."""
    options = [
        ("Setup / configure", "run the guided installer"),
        ("Status", "show bot, listener and session state"),
        ("Listen", "run the listener in this terminal"),
        ("Exit", ""),
    ]
    print()
    print(ui.accent("TeleCode"))
    print(ui.dim("local Telegram bridge for coding agents"))
    print()
    for index, (label, hint) in enumerate(options, 1):
        suffix = f"  {ui.dim(hint)}" if hint else ""
        print(f"  {ui.accent(str(index) + '.')} {label}{suffix}")
    print()
    print(ui.dim("1-4 select · q exit · Ctrl-C cancel"))
    try:
        answer = input("Select: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 130
    if answer in ("q", "quit", "exit", "4"):
        return 0
    if answer in ("1", "setup"):
        import subprocess
        installer = pathlib.Path(__file__).resolve().parent.parent / "install.sh"
        return subprocess.call(["bash", str(installer)])
    if answer in ("2", "status"):
        return cmd_status()
    if answer in ("3", "listen"):
        return tg.cmd_listen()
    print(f"Unknown choice: {answer}", file=sys.stderr)
    return 2


def cmd_install():
    """Install the current checkout as a user-level systemd service."""
    # This file lives one level below the repo root (telegram_bridge/cli.py),
    # so the installer anchor needs the extra parent.
    source = pathlib.Path(__file__).resolve().parent.parent
    script = source / "install.sh"
    if not script.is_file():
        print("installer not found; use the release install.sh", file=sys.stderr)
        return 2
    import subprocess
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
        import subprocess
        return subprocess.call([sys.executable, str(helper)])
    if len(sys.argv) > 1 and sys.argv[1] == "--init":
        import subprocess
        return subprocess.call(["bash", str(pathlib.Path(__file__).resolve().parent.parent / "install.sh")])
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        import subprocess
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
        import subprocess
        args = ["bash", str(pathlib.Path(__file__).resolve().parent.parent / "install.sh"), sys.argv[1]]
        return subprocess.call(args)
    cmds = {
        "listen": tg.cmd_listen, "read": cmd_read, "wait": cmd_wait,
        "send": cmd_send, "sendfile": cmd_sendfile, "status": cmd_status,
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
