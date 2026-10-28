#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/telegram-bridge"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/telegram-bridge"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

mkdir -p "$APP_DIR" "$CONFIG_DIR" "$UNIT_DIR"
install -m 0644 "$SOURCE_DIR/tg_bridge.py" "$APP_DIR/tg_bridge.py"
install -m 0644 "$SOURCE_DIR/tg_mcp.py" "$APP_DIR/tg_mcp.py"
install -m 0644 "$SOURCE_DIR/telegram-bridge.service" "$UNIT_DIR/telegram-bridge.service"

if [[ ! -f "$CONFIG_DIR/telegram.env" ]]; then
  install -m 0600 "$SOURCE_DIR/.env.example" "$CONFIG_DIR/telegram.env"
  echo "Edit $CONFIG_DIR/telegram.env with your private bot credentials, then rerun this script."
  exit 0
fi
chmod 0600 "$CONFIG_DIR/telegram.env"
systemctl --user daemon-reload
systemctl --user enable --now telegram-bridge.service
echo "Enabled. Check status with: systemctl --user status telegram-bridge"
