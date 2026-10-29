#!/usr/bin/env python3
"""Small private-chat helper that prints the caller's Telegram chat ID."""
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request


def main():
    env_path = pathlib.Path(os.environ.get(
        "TELEGRAM_BRIDGE_HOME",
        pathlib.Path(os.environ.get("XDG_CONFIG_HOME", pathlib.Path.home() / ".config"))
        / "telegram-bridge",
    )) / "telegram.env"
    if not env_path.is_file():
        raise SystemExit("TeleCode config is missing. Run `telecode setup` first.")
    lines = env_path.read_text(encoding="utf-8").splitlines()
    values = {}
    for line in lines:
        if line.strip().startswith("TG_BOT_TOKEN="):
            values["TG_BOT_TOKEN"] = line.split("=", 1)[1].strip().strip('"').strip("'")
        elif line.strip().startswith("TG_CHAT_ID="):
            values["TG_CHAT_ID"] = line.split("=", 1)[1].strip().strip('"').strip("'")
    token = values.get("TG_BOT_TOKEN", "")
    if not token:
        token = input("Telegram bot token from BotFather: ").strip()
        if not token:
            raise SystemExit("A bot token is required.")
        values["TG_BOT_TOKEN"] = token
        values.setdefault("TG_CHAT_ID", "")
        lines = [line for line in env_path.read_text(encoding="utf-8").splitlines()
                 if not line.startswith("TG_BOT_TOKEN=")]
        lines.append(f"TG_BOT_TOKEN={token}")
        _write_private(env_path, lines)

    api = f"https://api.telegram.org/bot{token}/"
    if "--bootstrap" in sys.argv:
        print("Start the bot chat and run `telecode get-id` in another terminal to receive your chat ID.")
        return 0

    if "--configure" in sys.argv:
        print("Open the bot's private chat and send /start. The owner ID will be saved automatically.")
    else:
        print("Open your bot's private chat and send /start. The helper will show an ID button.")
    offset = 0
    while True:
        req = urllib.request.Request(api + "getUpdates", urllib.parse.urlencode({
            "offset": offset, "timeout": 30,
            "allowed_updates": json.dumps(["message"]),
        }).encode())
        with urllib.request.urlopen(req, timeout=40) as response:
            payload = json.loads(response.read().decode("utf-8"))
        for update in payload.get("result", []):
            offset = int(update.get("update_id", 0)) + 1
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            sender = message.get("from") or {}
            if chat.get("type") != "private" or str(chat.get("id")) != str(sender.get("id")):
                continue
            chat_id = str(chat.get("id"))
            keyboard = json.dumps({"inline_keyboard": [[{
                "text": f"Copy chat ID: {chat_id}",
                "copy_text": {"text": chat_id},
            }]]})
            response = urllib.request.Request(api + "sendMessage", urllib.parse.urlencode({
                "chat_id": chat_id,
                "text": f"Your private chat ID is:\n<code>{chat_id}</code>\nCopy it into the TeleCode setup.",
                "parse_mode": "HTML",
                "reply_markup": keyboard,
            }).encode())
            with urllib.request.urlopen(response, timeout=20):
                pass
            print(f"Your private chat ID: {chat_id}")
            if "--configure" in sys.argv:
                values["TG_CHAT_ID"] = chat_id
                lines = [line for line in env_path.read_text(encoding="utf-8").splitlines()
                         if not line.startswith("TG_CHAT_ID=")]
                lines.append(f"TG_CHAT_ID={chat_id}")
                _write_private(env_path, lines)
                print("Owner chat ID saved to the private TeleCode configuration.")
    return 0


def _write_private(path, lines):
    import tempfile
    fd, name = tempfile.mkstemp(prefix=".telegram.env.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        time.sleep(0.2)


if __name__ == "__main__":
    sys.exit(main())
