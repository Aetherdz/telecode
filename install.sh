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
install -m 0644 "$SOURCE_DIR/adapters/base.py" "$APP_DIR/adapters/base.py"
install -m 0644 "$SOURCE_DIR/adapters/opencode.py" "$APP_DIR/adapters/opencode.py"
install -m 0644 "$SOURCE_DIR/adapters/claude_code.py" "$APP_DIR/adapters/claude_code.py"
install -m 0644 "$SOURCE_DIR/telegram-bridge.py" "$APP_DIR/telegram-bridge.py"
install -m 0644 "$SOURCE_DIR/SKILL.md" "$APP_DIR/SKILL.md"
install -m 0644 "$SOURCE_DIR/setup_cli.py" "$APP_DIR/setup_cli.py"
cat > "$BIN_DIR/telegram-bridge" <<EOF
#!/usr/bin/env bash
export TELEGRAM_BRIDGE_HOME="$CONFIG_DIR"
exec "$PYTHON" "$APP_DIR/telegram-bridge.py" "\$@"
EOF
chmod 0755 "$BIN_DIR/telegram-bridge"

if [[ ! -f "$CONFIG_DIR/telegram.env" ]]; then
  install -m 0600 "$SOURCE_DIR/.env.example" "$CONFIG_DIR/telegram.env"
  echo "Created private config: $CONFIG_DIR/telegram.env"
  echo "Edit it with TG_BOT_TOKEN and TG_CHAT_ID, then run: telegram-bridge install --enable"
  exit 0
fi
chmod 0600 "$CONFIG_DIR/telegram.env"

cat <<EOF
Installed to: $APP_DIR
Private config: $CONFIG_DIR/telegram.env
CLI: $BIN_DIR/telegram-bridge
Skill: $APP_DIR/SKILL.md
EOF

if [[ "${1:-}" != "--enable" && "${1:-}" != "--configure-cli" ]]; then
  read -r -p "Configure a detected coding-agent CLI now? [y/N] " configure
  if [[ "$configure" == "y" || "$configure" == "Y" ]]; then
    TELEGRAM_BRIDGE_APP_DIR="$APP_DIR" "$PYTHON" "$APP_DIR/setup_cli.py"
  fi
fi

if [[ "${1:-}" == "--enable" ]]; then
  mkdir -p "$UNIT_DIR"
  if [[ ! -f "$CONFIG_DIR/telegram.env" ]] || grep -Eq '^TG_BOT_TOKEN=$|^TG_CHAT_ID=$' "$CONFIG_DIR/telegram.env"; then
    echo "Set TG_BOT_TOKEN and TG_CHAT_ID in $CONFIG_DIR/telegram.env before enabling." >&2
    exit 1
  fi
  mkdir -p "$UNIT_DIR"
  sed -e "s|%h/.config/telegram-bridge|$CONFIG_DIR|g" \
      -e "s|%h/.local/share/telegram-bridge|$APP_DIR|g" \
      "$SOURCE_DIR/telegram-bridge.service" > "$UNIT_DIR/telegram-bridge.service"
  chmod 0644 "$UNIT_DIR/telegram-bridge.service"
  systemctl --user daemon-reload
  systemctl --user enable --now telegram-bridge.service
  echo "Enabled user startup service: telegram-bridge"
fi

if [[ "${1:-}" == "--configure-cli" ]]; then
  TELEGRAM_BRIDGE_APP_DIR="$APP_DIR" "$PYTHON" "$APP_DIR/setup_cli.py"
fi
