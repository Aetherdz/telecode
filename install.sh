#!/usr/bin/env bash
set -euo pipefail

# One-line bootstrap downloads the reviewed installer from this public repository.
# Its normal source-checkout mode still copies the full project and remains inspectable.
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

show_download_progress() {
  local progress=$1
  local filled=$((progress / 10))
  local bar
  printf -v bar '%*s' "$filled" ''
  bar=${bar// /#}
  printf '\r[%3d%%] [%-10s]' "$progress" "$bar"
}

if [[ "${1:-}" == "--curl-bootstrap" ]]; then
  shift
  if [[ $# -gt 0 ]]; then
    echo "--curl-bootstrap does not accept extra arguments." >&2
    exit 2
  fi
  if ! command -v git >/dev/null 2>&1; then
    echo "git is required to fetch the TeleCode source." >&2
    exit 2
  fi
  logo
  printf '\n↓ Downloading TeleCode source\n'
  bootstrap_dir="${XDG_CACHE_HOME:-$HOME/.cache}/telecode-bootstrap"
  mkdir -p "$bootstrap_dir"
  chmod 700 "$bootstrap_dir"
  if [[ -e "$bootstrap_dir/repo" && ! -d "$bootstrap_dir/repo/.git" ]]; then
    echo "Bootstrap path exists but is not a TeleCode checkout: $bootstrap_dir/repo" >&2
    exit 2
  fi
  if ! git -C "$bootstrap_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git clone --quiet --depth 1 https://github.com/Aetherdz/telecode.git "$bootstrap_dir/repo" || {
      rm -rf "$bootstrap_dir/repo"
      exit 2
    }
  else
    git -C "$bootstrap_dir/repo" fetch --quiet --depth 1 origin main || exit 2
    git -C "$bootstrap_dir/repo" reset --hard FETCH_HEAD || exit 2
  fi
  show_download_progress 100
  printf '\n%s\n' '[100%] Download complete.' 'Starting TeleCode setup...' ''
  exec bash "$bootstrap_dir/repo/install.sh"
fi

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

logo
printf 'TeleCode installer %s\n\n' "$VERSION"
if [[ "${1:-}" == "--update" && "$(realpath "$SOURCE_DIR")" == "$(realpath "$APP_DIR")" ]]; then
  echo "Run ./install.sh --update from a source checkout, not the installed copy." >&2
  exit 2
fi
mkdir -p "$APP_DIR/adapters" "$APP_DIR/config" "$CONFIG_DIR" "$BIN_DIR"
install_if_changed() {
  local source="$1" destination="$2"
  if [[ "$source" -ef "$destination" ]]; then return 0; fi
  install -m 0644 "$source" "$destination"
}
install_if_changed "$SOURCE_DIR/tg_bridge.py" "$APP_DIR/tg_bridge.py"
install_if_changed "$SOURCE_DIR/tg_mcp.py" "$APP_DIR/tg_mcp.py"
install_if_changed "$SOURCE_DIR/install.sh" "$APP_DIR/install.sh"
install_if_changed "$SOURCE_DIR/adapters/base.py" "$APP_DIR/adapters/base.py"
install_if_changed "$SOURCE_DIR/adapters/__init__.py" "$APP_DIR/adapters/__init__.py"
install_if_changed "$SOURCE_DIR/adapters/opencode.py" "$APP_DIR/adapters/opencode.py"
install_if_changed "$SOURCE_DIR/adapters/claude_code.py" "$APP_DIR/adapters/claude_code.py"
install_if_changed "$SOURCE_DIR/telegram-bridge.py" "$APP_DIR/telegram-bridge.py"
install_if_changed "$SOURCE_DIR/telegram-bridge.service" "$APP_DIR/telegram-bridge.service"
install_if_changed "$SOURCE_DIR/SKILL.md" "$APP_DIR/SKILL.md"
install_if_changed "$SOURCE_DIR/setup_cli.py" "$APP_DIR/setup_cli.py"
install_if_changed "$SOURCE_DIR/get_telegram_id.py" "$APP_DIR/get_telegram_id.py"
install_if_changed "$SOURCE_DIR/.env.example" "$APP_DIR/.env.example"
mkdir -p "$CONFIG_DIR/files"
for template in "$SOURCE_DIR"/config/*.example.json; do
  [[ -f "$template" ]] && install_if_changed "$template" "$APP_DIR/config/$(basename "$template")"
done
WRAPPER_TMP="$(mktemp "$BIN_DIR/.telecode.XXXXXX")"
cat > "$WRAPPER_TMP" <<'EOF'
#!/usr/bin/env bash
APP_DIR="${TELECODE_APP_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/telegram-bridge}"
export TELEGRAM_BRIDGE_HOME="${TELEGRAM_BRIDGE_HOME:-${XDG_CONFIG_HOME:-$HOME/.config}/telegram-bridge}"
export TELECODE_APP_DIR="${TELECODE_APP_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/telegram-bridge}"
APP_DIR="$TELECODE_APP_DIR"
if [[ ! -d "$APP_DIR" ]]; then
  echo "TeleCode files not found at $APP_DIR; rerun the source installer." >&2
  exit 2
fi
if [[ "$#" -eq 1 && ( "$1" == "--help" || "$1" == "help" ) ]]; then exec bash "$APP_DIR/install.sh" help; fi
if [[ "$#" -eq 1 && "$1" == "setup" ]]; then exec bash "$APP_DIR/install.sh"; fi
if [[ "$#" -eq 1 && "$1" == "update" ]]; then printf 'Update from a TeleCode source checkout with: ./install.sh --update\n' >&2; exit 2; fi
if [[ "$#" -eq 1 && "$1" == "--configure-cli" ]]; then exec bash "$APP_DIR/install.sh" --configure-cli; fi
if [[ "$#" -eq 1 && ( "$1" == "--enable" || "$1" == "--start" || "$1" == "--status" || "$1" == "listen" || "$1" == "status" ) ]]; then exec bash "$APP_DIR/install.sh" "$1"; fi
if [[ "$#" -ge 1 && "$1" == "get-id" ]]; then shift; exec python3 "$APP_DIR/get_telegram_id.py" "$@"; fi
exec python3 "$APP_DIR/telegram-bridge.py" "$@"
EOF
chmod 0755 "$WRAPPER_TMP"
mv -f "$WRAPPER_TMP" "$BIN_DIR/telecode"
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
if [[ "${1:-}" == "--update" ]]; then
  echo "Updating TeleCode from source; private configuration is preserved."
  UPDATE_MODE=1
fi

if [[ "${1:-}" == "--uninstall" ]]; then
  echo "Uninstall is not automated. Disable the service, then remove $APP_DIR and $BIN_DIR/telecode; config at $CONFIG_DIR is preserved." >&2
  exit 2
fi

if [[ "${1:-}" == "--help" || "${1:-}" == "help" ]]; then
  cat <<'EOF'
TeleCode guided setup and commands:
  telecode setup        configure a CLI and collect Telegram credentials
  telecode get-id       detect your private chat ID through your own bot
  telecode status       show listener status
  telecode listen       run the listener in this terminal
  telecode help         show this help

Create a bot with @BotFather and keep its token private. For your numeric
account ID, message @Getmyid_bot, or choose automatic detection and send /start
to your own bot. Never send your bot token to an ID lookup bot.
EOF
  exit 0
fi

if [[ "${1:-}" == "--enable" ]]; then
  if [[ ! -f "$CONFIG_DIR/telegram.env" ]] || \
     ! grep -Eq '^TG_BOT_TOKEN=[0-9]{5,}:[A-Za-z0-9_-]{20,}$' "$CONFIG_DIR/telegram.env" || \
      ! grep -Eq '^TG_CHAT_ID=-?[0-9]+$' "$CONFIG_DIR/telegram.env"; then
    echo "Set a valid TG_BOT_TOKEN (from @BotFather) and numeric TG_CHAT_ID in $CONFIG_DIR/telegram.env before enabling." >&2
    exit 1
  fi
  if [[ "$CONFIG_DIR$APP_DIR" =~ [[:space:]] || "$CONFIG_DIR$APP_DIR" == *'|'* || "$CONFIG_DIR$APP_DIR" == *'&'* || "$CONFIG_DIR$APP_DIR" == *'\'* || "$CONFIG_DIR$APP_DIR" == *'%'* || "$CONFIG_DIR$APP_DIR" == *'"'* || "$CONFIG_DIR$APP_DIR" == *$'\n'* ]]; then
    echo 'Systemd setup does not support whitespace or |, &, backslash, %, double quote, or newline in XDG paths.' >&2
    exit 2
  fi
  mkdir -p "$UNIT_DIR"
  TMP_UNIT="$(mktemp "$UNIT_DIR/.telegram-bridge.service.XXXXXX")"
  sed -e "s|%h/.config/telegram-bridge|$(printf '%s' "$CONFIG_DIR" | sed 's/[&|\\]/\\&/g')|g" \
      -e "s|%h/.local/share/telegram-bridge|$(printf '%s' "$APP_DIR" | sed 's/[&|\\]/\\&/g')|g" \
      "$APP_DIR/telegram-bridge.service" > "$TMP_UNIT"
  chmod 0644 "$TMP_UNIT"
  mv -f "$TMP_UNIT" "$UNIT_DIR/telegram-bridge.service"
  systemctl --user daemon-reload
  systemctl --user enable --now telegram-bridge.service
  echo "Enabled user startup service: telegram-bridge"
fi

if [[ "${UPDATE_MODE:-0}" == "1" ]]; then
  echo "Updated installed files in $APP_DIR. Private configuration was preserved."
  exit 0
fi

if [[ "${1:-}" == "--start" ]]; then
  TELEGRAM_BRIDGE_HOME="$CONFIG_DIR" exec "$PYTHON" "$APP_DIR/telegram-bridge.py" listen
fi
if [[ "${1:-}" == "listen" ]]; then
  TELEGRAM_BRIDGE_HOME="$CONFIG_DIR" exec "$PYTHON" "$APP_DIR/telegram-bridge.py" listen
fi

if [[ "${1:-}" == "--status" ]]; then
  TELEGRAM_BRIDGE_HOME="$CONFIG_DIR" exec "$PYTHON" "$APP_DIR/telegram-bridge.py" status
fi
if [[ "${1:-}" == "status" ]]; then
  TELEGRAM_BRIDGE_HOME="$CONFIG_DIR" exec "$PYTHON" "$APP_DIR/telegram-bridge.py" status
fi

if [[ "${1:-}" == "--configure-cli" ]]; then
  TELEGRAM_BRIDGE_APP_DIR="$APP_DIR" "$PYTHON" "$APP_DIR/setup_cli.py"
  exit $?
fi


if [[ "${1:-}" == "get-id" ]]; then
  shift
  exec "$PYTHON" "$APP_DIR/get_telegram_id.py" "$@"
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
  if ! grep -Eq '^TG_BOT_TOKEN=[0-9]{5,}:[A-Za-z0-9_-]{20,}$' "$CONFIG_DIR/telegram.env"; then
    read -r -s -p "Telegram bot token (from @BotFather): " token
    printf '\n'
    [[ "$token" =~ ^[0-9]{5,}:[A-Za-z0-9_-]{20,}$ ]] || { echo "Invalid Telegram bot token format; obtain it from @BotFather." >&2; exit 2; }
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
  if ! grep -Eq '^TG_CHAT_ID=-?[0-9]+$' "$CONFIG_DIR/telegram.env"; then
    echo "To find your ID, message @Getmyid_bot, then enter it below; or choose auto-detection." >&2
    printf 'Numeric Telegram owner chat ID (or A for automatic bot detection): '
    read -r chat_id
    if [[ "$chat_id" =~ ^-?[0-9]+$ ]]; then
      CHAT_ID="$chat_id" "$PYTHON" - "$CONFIG_DIR/telegram.env" <<'PY'
import os, pathlib, sys, tempfile
path = pathlib.Path(sys.argv[1])
lines = [line for line in path.read_text().splitlines() if not line.startswith("TG_CHAT_ID=")]
lines.append("TG_CHAT_ID=" + os.environ["CHAT_ID"])
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
    elif [[ "$chat_id" =~ ^[Aa]$ ]]; then
      TELEGRAM_BRIDGE_HOME="$CONFIG_DIR" "$PYTHON" "$APP_DIR/get_telegram_id.py" --configure
    else
      echo "Enter a numeric chat ID or A. No service was enabled." >&2
      exit 2
    fi
  fi
  if ! grep -Eq '^TG_CHAT_ID=-?[0-9]+$' "$CONFIG_DIR/telegram.env"; then
    echo "Owner chat ID was not saved; listener will not be enabled." >&2
    exit 2
  fi
  if [[ "$CONFIG_DIR$APP_DIR" =~ [[:space:]] || "$CONFIG_DIR$APP_DIR" == *'|'* || "$CONFIG_DIR$APP_DIR" == *'&'* || "$CONFIG_DIR$APP_DIR" == *'\'* || "$CONFIG_DIR$APP_DIR" == *'%'* || "$CONFIG_DIR$APP_DIR" == *'"'* || "$CONFIG_DIR$APP_DIR" == *$'\n'* ]]; then
    echo 'Systemd setup does not support whitespace or |, &, backslash, %, double quote, or newline in XDG paths.' >&2
    exit 2
  fi
  mkdir -p "$UNIT_DIR"
  TMP_UNIT="$(mktemp "$UNIT_DIR/.telegram-bridge.service.XXXXXX")"
  sed -e "s|%h/.config/telegram-bridge|$(printf '%s' "$CONFIG_DIR" | sed 's/[&|\\]/\\&/g')|g" \
      -e "s|%h/.local/share/telegram-bridge|$(printf '%s' "$APP_DIR" | sed 's/[&|\\]/\\&/g')|g" \
      "$APP_DIR/telegram-bridge.service" > "$TMP_UNIT"
  chmod 0644 "$TMP_UNIT"
  mv -f "$TMP_UNIT" "$UNIT_DIR/telegram-bridge.service"
  systemctl --user daemon-reload
  systemctl --user enable --now telegram-bridge.service
  echo "Setup complete: MCP configured and TeleCode enabled at login. Restart the selected CLI to load MCP."
  exit 0
fi

echo "Usage: install.sh [--bootstrap|--update|--enable|--start|--status|--configure-cli|get-id]" >&2
exit 2
