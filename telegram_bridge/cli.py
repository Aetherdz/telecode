"""Command-line entry points for the bridge."""
import os
import pathlib
import subprocess
import sys
import time

import telegram_bridge as tg

USAGE = ("usage: telecode {setup|listen|read|wait SECONDS|send TEXT|"
         "sendfile PATH [CAPTION]|status|get-id|--enable|--configure-cli}")


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
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    deadline = time.time() + seconds
    while time.time() < deadline:
        recs = tg._unread()
        if recs:
            for r in recs:
                line = f"[{r['iso']}] {r['text']}"
                if r.get("file"):
                    line += f"\n    FILE: {r['file']}"
                print(line)
            tg._advance(recs)
            return 0
        time.sleep(2)
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
    me = tg.api(cfg["TG_BOT_TOKEN"], "getMe", timeout=15)
    bot = me.get("result") or {}
    alive = "down"
    if tg.PID.exists():
        pid = tg.PID.read_text().strip()
        try:
            os.kill(int(pid), 0)
            alive = f"up (pid {pid})"
        except Exception:
            alive = f"stale pid {pid}"
    print(f"bot: @{bot.get('username')} (id {bot.get('id')})")
    print(f"owner chat: {cfg.get('TG_CHAT_ID')}")
    print(f"listener: {alive}")
    sid, how = tg.resolve_session(cfg)
    print(f"inject target: {sid or '(none)'} [{how}]")
    print(f"delivery: {cfg.get('TG_DELIVERY') or 'steer'} (session mode: {cfg.get('OPENCODE_SESSION_MODE') or 'auto'})")
    if tg.STATE.exists():
        print(f"last delivered session: {tg.STATE.read_text().strip()}")
    print(f"unread: {len(tg._unread())}")
    return 0


def cmd_install():
    """Install the current checkout as a user-level systemd service."""
    # This file lives one level below the repo root (telegram_bridge/cli.py),
    # so the installer anchor needs the extra parent.
    source = pathlib.Path(__file__).resolve().parent.parent
    script = source / "install.sh"
    if not script.is_file():
        print("installer not found; use the release install.sh", file=sys.stderr)
        return 2
    return subprocess.call(["bash", str(script), "--enable"])


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "get-id":
        helper = pathlib.Path(__file__).resolve().parent.parent / "get_telegram_id.py"
        if not helper.is_file():
            print("chat ID helper is not installed; reinstall TeleCode", file=sys.stderr)
            return 2
        return subprocess.call([sys.executable, str(helper)])
    if len(sys.argv) > 1 and sys.argv[1] == "--init":
        return subprocess.call(["bash", str(pathlib.Path(__file__).resolve().parent.parent / "install.sh")])
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        return subprocess.call(["bash", str(pathlib.Path(__file__).resolve().parent.parent / "install.sh")])
    if len(sys.argv) > 1 and sys.argv[1] in ("--enable", "--configure-cli"):
        args = ["bash", str(pathlib.Path(__file__).resolve().parent.parent / "install.sh"), sys.argv[1]]
        return subprocess.call(args)
    cmds = {
        "listen": tg.cmd_listen, "read": cmd_read, "wait": cmd_wait,
        "send": cmd_send, "sendfile": cmd_sendfile, "status": cmd_status,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(USAGE, file=sys.stderr)
        return 2
    return cmds[sys.argv[1]]() or 0
