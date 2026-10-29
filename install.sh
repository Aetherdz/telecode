#!/usr/bin/env bash
set -euo pipefail

VERSION="0.1.0"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/telegram-bridge"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/telegram-bridge"
BIN_DIR="${HOME}/.local/bin"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$(command -v python3 || true)"
if [[ -z "$PYTHON" ]] || ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11+ is required; no install changes made." >&2
  exit 1
fi

logo() {
  local main="" reset=""
  if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    main=$'\033[38;2;48;179;239m'
    reset=$'\033[0m'
  fi
  printf '%s\n' "${main}▀▀█▀▀ █▀▀▀▀ █     █▀▀▀▀ ▄▀▀▀▀ ▄▀▀▀▄ █▀▀▀▄ █▀▀▀▀${reset}"
  printf '%s\n' "${main}  █   █▄▄▄  █     █▄▄▄  █     █   █ █   █ █▄▄▄ ${reset}"
  printf '%s\n' "${main}  █   █     █     █     █     █   █ █   █ █    ${reset}"
  printf '%s\n' "${main}  ▀   ▀▀▀▀▀ ▀▀▀▀▀ ▀▀▀▀▀  ▀▀▀▀  ▀▀▀  ▀▀▀▀  ▀▀▀▀▀${reset}"
  printf '  Telegram ⇄ OpenCode & any CLI\n'
}

logo
printf 'TeleCode installer %s\n\n' "$VERSION"
mkdir -p "$APP_DIR/adapters" "$CONFIG_DIR" "$BIN_DIR"
install -m 0644 "$SOURCE_DIR/tg_bridge.py" "$APP_DIR/tg_bridge.py"
install -m 0644 "$SOURCE_DIR/tg_mcp.py" "$APP_DIR/tg_mcp.py"
install -m 0644 "$SOURCE_DIR/install.sh" "$APP_DIR/install.sh"
install -m 0644 "$SOURCE_DIR/adapters/base.py" "$APP_DIR/adapters/base.py"
install -m 0644 "$SOURCE_DIR/adapters/opencode.py" "$APP_DIR/adapters/opencode.py"
install -m 0644 "$SOURCE_DIR/adapters/claude_code.py" "$APP_DIR/adapters/claude_code.py"
install -m 0644 "$SOURCE_DIR/telegram-bridge.py" "$APP_DIR/telegram-bridge.py"
install -m 0644 "$SOURCE_DIR/telegram-bridge.service" "$APP_DIR/telegram-bridge.service"
install -m 0644 "$SOURCE_DIR/SKILL.md" "$APP_DIR/SKILL.md"
install -m 0644 "$SOURCE_DIR/setup_cli.py" "$APP_DIR/setup_cli.py"
install -m 0644 "$SOURCE_DIR/get_telegram_id.py" "$APP_DIR/get_telegram_id.py"
cat > "$BIN_DIR/telecode" <<EOF
#!/usr/bin/env bash
export TELEGRAM_BRIDGE_HOME="$CONFIG_DIR"
if [[ "\$#" -eq 1 && "\$1" == "--enable" ]]; then
  exec bash "$APP_DIR/install.sh" --enable
fi
if [[ "\$#" -eq 1 && "\$1" == "--start" ]]; then
  exec bash "$APP_DIR/install.sh" --start
fi
if [[ "\$#" -eq 1 && "\$1" == "--status" ]]; then
  exec bash "$APP_DIR/install.sh" --status
fi
if [[ "\$#" -eq 1 && "\$1" == "--help" ]]; then
  printf 'Usage: telecode setup | status | get-id | listen | read | wait SECONDS | send TEXT | sendfile PATH [CAPTION]\n'
  exit 0
fi
if [[ "\$#" -eq 1 && "\$1" == "--configure-cli" ]]; then
  exec bash "$APP_DIR/install.sh" --configure-cli
fi
  if [[ "\$#" -eq 1 && ( "\$1" == "setup" || "\$1" == "--init" ) ]]; then
  exec bash "$APP_DIR/install.sh"
fi
if [[ "\$#" -eq 1 && "\$1" == "get-id" ]]; then
  exec "$PYTHON" "$APP_DIR/get_telegram_id.py"
fi
exec "$PYTHON" "$APP_DIR/telegram-bridge.py" "\$@"
EOF
chmod 0755 "$BIN_DIR/telecode"

if [[ ! -f "$CONFIG_DIR/telegram.env" ]]; then
  install -m 0600 "$SOURCE_DIR/.env.example" "$CONFIG_DIR/telegram.env"
fi
chmod 0600 "$CONFIG_DIR/telegram.env"

cat <<EOF
Installed to: $APP_DIR
Private config: $CONFIG_DIR/telegram.env
CLI: $BIN_DIR/telecode
Skill: $APP_DIR/SKILL.md
EOF

if [[ "${1:-}" == "--bootstrap" ]]; then
  exit 0
fi

if [[ "${1:-}" == "--enable" ]]; then
  if [[ ! -f "$CONFIG_DIR/telegram.env" ]] || grep -Eq '^TG_BOT_TOKEN=$|^TG_CHAT_ID=$' "$CONFIG_DIR/telegram.env"; then
    echo "Set TG_BOT_TOKEN and TG_CHAT_ID in $CONFIG_DIR/telegram.env before enabling." >&2
    exit 1
  fi
  mkdir -p "$UNIT_DIR"
  sed -e "s|%h/.config/telegram-bridge|$CONFIG_DIR|g" \
      -e "s|%h/.local/share/telegram-bridge|$APP_DIR|g" \
      "$APP_DIR/telegram-bridge.service" > "$UNIT_DIR/telegram-bridge.service"
  chmod 0644 "$UNIT_DIR/telegram-bridge.service"
  systemctl --user daemon-reload
  systemctl --user enable --now telegram-bridge.service
  echo "Enabled user startup service: telegram-bridge"
fi

if [[ "${1:-}" == "--start" ]]; then
  TELEGRAM_BRIDGE_HOME="$CONFIG_DIR" exec "$PYTHON" "$APP_DIR/telegram-bridge.py" listen
fi

if [[ "${1:-}" == "--status" ]]; then
  TELEGRAM_BRIDGE_HOME="$CONFIG_DIR" exec "$PYTHON" "$APP_DIR/telegram-bridge.py" status
fi

if [[ "${1:-}" == "--configure-cli" ]]; then
  TELEGRAM_BRIDGE_APP_DIR="$APP_DIR" "$PYTHON" "$APP_DIR/setup_cli.py"
  exit $?
fi

if [[ "${1:-}" == "get-id" ]]; then
  exec "$PYTHON" "$APP_DIR/get_telegram_id.py"
fi

if [[ $# -eq 0 ]]; then
  if [[ ! -t 0 ]]; then
    echo "Interactive setup requires a terminal. Rerun install.sh in a terminal." >&2
    exit 2
  fi
  TELEGRAM_BRIDGE_APP_DIR="$APP_DIR" "$PYTHON" "$APP_DIR/setup_cli.py" || {
    echo "CLI integration was cancelled or could not be configured; listener was not enabled." >&2
    exit 2
  }
  if ! grep -q '^TG_BOT_TOKEN=.' "$CONFIG_DIR/telegram.env"; then
    read -r -s -p "Telegram bot token (from BotFather): " token
    printf '\n'
    [[ -n "$token" ]] || { echo "A bot token is required." >&2; exit 2; }
    TOKEN="$token" "$PYTHON" - "$CONFIG_DIR/telegram.env" <<'PY'
import os, pathlib, sys, tempfile
path = pathlib.Path(sys.argv[1])
lines = [line for line in path.read_text().splitlines() if not line.startswith("TG_BOT_TOKEN=")]
lines.append("TG_BOT_TOKEN=" + os.environ["TOKEN"])
fd, name = tempfile.mkstemp(prefix=".telegram.env.", dir=path.parent)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("\n".join(lines) + "\n")
        stream.flush(); os.fsync(stream.fileno())
    os.replace(name, path)
finally:
    try: os.unlink(name)
    except FileNotFoundError: pass
PY
  fi
  if ! grep -q '^TG_CHAT_ID=.' "$CONFIG_DIR/telegram.env"; then
  TELEGRAM_BRIDGE_HOME="$CONFIG_DIR" "$PYTHON" "$APP_DIR/get_telegram_id.py" --configure
  fi
  if ! grep -q '^TG_CHAT_ID=.' "$CONFIG_DIR/telegram.env"; then
    echo "Owner chat ID was not saved; listener will not be enabled." >&2
    exit 2
  fi
  mkdir -p "$UNIT_DIR"
  sed -e "s|%h/.config/telegram-bridge|$CONFIG_DIR|g" \
      -e "s|%h/.local/share/telegram-bridge|$APP_DIR|g" \
      "$APP_DIR/telegram-bridge.service" > "$UNIT_DIR/telegram-bridge.service"
  chmod 0644 "$UNIT_DIR/telegram-bridge.service"
  systemctl --user daemon-reload
  systemctl --user enable --now telegram-bridge.service
  echo "Setup complete: MCP configured and TeleCode enabled at login. Restart the selected CLI to load MCP."
  exit 0
fi

echo "Usage: install.sh [--bootstrap|--enable|--start|--status|--configure-cli|get-id]" >&2
exit 2
