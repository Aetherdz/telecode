#!/usr/bin/env bash
set -Eeuo pipefail

# TeleCode installer.
#
# Interactive/source mode copies the reviewed project files into place and runs
# guided setup. The one-line mode (`curl -fsSL <url> | bash`) downloads a pinned
# GitHub tarball, verifies its SHA-256, extracts it into a private temporary
# directory, and then starts the same guided setup. No branch (main/master) is
# ever fetched implicitly; use a tag or a full commit id.

VERSION="0.1.0"
REPO_OWNER="Aetherdz"
REPO_NAME="telecode"

# Pinned release identity. Update all three values together when publishing.
PINNED_REF="5a28ad3a5c048c3541dd0c5ee1e83f5c1d05ed99"
PINNED_SHA256="9ec3f96b0e742a6c2db82e12e5eea8a70af361bc2e5db086d552822afe2f5dfb"
PINNED_SIZE="1376753"

VERBOSE=0
QUIET=0
ASSUME_YES=0
DRY_RUN=0
BOOTSTRAP_FLAG=0
COMMAND=""
GETID_ARGS=()
CHANGED_FILES=0

UI_TTY=0
if [[ -t 1 ]]; then UI_TTY=1; fi
C_RESET=""
C_BOLD=""
C_DIM=""
C_GREEN=""
C_RED=""
C_YELLOW=""
ICON_OK="ok"
ICON_FAIL="error"
ICON_WARN="!"
if [[ "$UI_TTY" == "1" && -z "${NO_COLOR:-}" && "${TERM:-}" != "dumb" ]]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
  C_DIM=$'\033[2m'
  C_GREEN=$'\033[32m'
  C_RED=$'\033[31m'
  C_YELLOW=$'\033[33m'
  case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *[Uu][Tt][Ff]-8*|*[Uu][Tt][Ff]8*) ICON_OK="✓"; ICON_FAIL="✗" ;;
  esac
fi

TEMP_PATHS=()
TMP_DIR=""

# shellcheck disable=SC2317  # invoked by the EXIT trap
cleanup() {
  local path
  for path in "${TEMP_PATHS[@]+"${TEMP_PATHS[@]}"}"; do
    [[ -n "$path" ]] && rm -rf -- "$path"
  done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

register_temp() {
  TEMP_PATHS[${#TEMP_PATHS[@]}]="$1"
}

ensure_tmp() {
  if [[ -z "$TMP_DIR" ]]; then
    TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/telecode.XXXXXX")"
    chmod 700 "$TMP_DIR"
    register_temp "$TMP_DIR"
  fi
}

title() {
  (( QUIET )) && return 0
  printf '\n%s%s%s\n' "$C_BOLD" "$*" "$C_RESET"
}

ok() {
  (( QUIET )) && return 0
  printf '%s%s%s %s\n' "$C_GREEN" "$ICON_OK" "$C_RESET" "$*"
}

warn() {
  (( QUIET )) && return 0
  printf '%s%s%s %s\n' "$C_YELLOW" "$ICON_WARN" "$C_RESET" "$*" >&2
}

fail() {
  printf '%s%s%s %s\n' "$C_RED" "$ICON_FAIL" "$C_RESET" "$*" >&2
}

note() {
  (( QUIET )) && return 0
  printf '%s%s%s\n' "$C_DIM" "$*" "$C_RESET"
}

dry() {
  (( QUIET )) && return 0
  printf '%s[dry-run]%s %s\n' "$C_DIM" "$C_RESET" "$*"
}

usage() {
  cat <<'EOF'
Usage: install.sh [options] [command]

Commands:
  (none)              guided setup: install files, configure a CLI, collect credentials
  --update            refresh installed files; private config is preserved
  --enable            enable the per-user startup service
  --uninstall         remove the startup service; keep app and config
  --start, listen     run the listener in this terminal
  --status, status    show listener status
  --configure-cli     configure a coding-agent CLI (MCP registration)
  --web               temporary loopback-only browser setup wizard
  --cli               terminal setup wizard
  --browser-setup     alias for --web
  get-id              detect your private chat ID through your own bot
  --bootstrap         install files only (used by package managers/tests)

Options:
  --verbose           stream command output instead of capturing it
  --quiet             errors only
  --yes, -y           non-interactive: never prompt for credentials
  --dry-run           show planned changes without writing anything
  --version           print the installer version
  --help, -h          show this help
  --curl-bootstrap    one-line mode: fetch a pinned, SHA-256-verified tarball
EOF
}

# ---------------------------------------------------------------- bootstrap --
logo() {
  (( QUIET )) && return 0
  local main="" reset=""
  if [[ "$UI_TTY" == "1" && -z "${NO_COLOR:-}" && "${TERM:-}" != "dumb" ]]; then
    main=$'\033[38;2;48;179;239m'
    reset=$'\033[0m'
  fi
  printf '%s\n' "${main}▀▀█▀▀ █▀▀▀▀ █     █▀▀▀▀ ▄▀▀▀▀ ▄▀▀▀▄ █▀▀▀▄ █▀▀▀▀${reset}"
  printf '%s\n' "${main}  █   █▄▄▄  █     █▄▄▄  █     █   █ █   █ █▄▄▄ ${reset}"
  printf '%s\n' "${main}  █   █     █     █     █     █   █ █   █ █    ${reset}"
  printf '%s\n' "${main}  ▀   ▀▀▀▀▀ ▀▀▀▀▀ ▀▀▀▀▀  ▀▀▀▀  ▀▀▀  ▀▀▀▀  ▀▀▀▀▀${reset}"
  printf '  Telegram ⇄ OpenCode & any CLI\n'
}

format_bytes() {
  local bytes="${1:-0}"
  if (( bytes >= 1073741824 )); then
    printf '%d.%d GB' $((bytes / 1073741824)) $(((bytes % 1073741824) * 10 / 1073741824))
  elif (( bytes >= 1048576 )); then
    printf '%d.%d MB' $((bytes / 1048576)) $(((bytes % 1048576) * 10 / 1048576))
  elif (( bytes >= 1024 )); then
    printf '%d KB' $((bytes / 1024))
  else
    printf '%d B' "$bytes"
  fi
}

# One real progress line, TTY only. Percentage is printed only when the total
# size is known (pinned manifest or Content-Length); otherwise only real bytes.
render_progress() {
  local percent="$1" have_percent="$2" size="$3" total="$4"
  local width=24 filled bar pad color="" reset=""
  [[ -t 2 ]] || return 0
  if [[ -z "${NO_COLOR:-}" && "${TERM:-}" != "dumb" ]]; then
    color=$'\033[2m'
    reset=$'\033[0m'
  fi
  if [[ "$have_percent" == "1" && "$total" -gt 0 ]]; then
    filled=$((percent * width / 100))
    (( filled > width )) && filled=$width
    printf -v bar '%*s' "$filled" ''
    bar=${bar// /#}
    printf -v pad '%*s' $((width - filled)) ''
    printf '\r%s[%3d%%] [%s%s] %s / %s%s\033[K' \
      "$color" "$percent" "$bar" "$pad" "$(format_bytes "$size")" "$(format_bytes "$total")" "$reset" >&2
  else
    printf '\r%sDownloading TeleCode source: %s%s\033[K' \
      "$color" "$(format_bytes "$size")" "$reset" >&2
  fi
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "$1" | awk '{print $NF}'
  else
    return 1
  fi
}

content_length() {
  local url="$1" length
  length="$(curl -fsSI --connect-timeout 20 "$url" 2>/dev/null \
    | tr -d '\r' \
    | awk 'tolower($1) == "content-length:" { value = $2 } END { print value }')"
  if [[ "$length" =~ ^[0-9]+$ ]] && (( length > 0 )); then
    printf '%s' "$length"
  fi
}

# Download with live progress. All secondary output goes to the log file and is
# shown only when the transfer fails.
download_with_progress() {
  local url="$1" destination="$2" total="$3" log="$4"
  local part="${destination}.part" pid size percent

  rm -f -- "$part"
  curl -fsSL --retry 3 --retry-delay 1 --connect-timeout 20 \
    -o "$part" "$url" >>"$log" 2>&1 &
  pid=$!

  while kill -0 "$pid" 2>/dev/null; do
    if [[ -f "$part" ]]; then
      size="$(wc -c < "$part" | tr -d ' ')"
    else
      size=0
    fi
    if [[ -n "$total" && "$total" -gt 0 ]]; then
      percent=$((size * 100 / total))
      (( percent > 100 )) && percent=100
      render_progress "$percent" 1 "$size" "$total"
    else
      render_progress 0 0 "$size" 0
    fi
    sleep 0.2 2>/dev/null || sleep 1
  done

  if ! wait "$pid"; then
    [[ -t 2 ]] && printf '\n' >&2
    return 1
  fi

  if [[ -f "$part" ]]; then
    size="$(wc -c < "$part" | tr -d ' ')"
  else
    size=0
  fi
  if [[ -n "$total" && "$total" -gt 0 ]]; then
    render_progress 100 1 "$size" "$total"
    [[ -t 2 ]] && printf '\n' >&2
  elif [[ -t 2 ]]; then
    printf '\n' >&2
  fi
  mv -f -- "$part" "$destination"
}

checksum_for_ref() {
  local ref="$1" sidecar="$TMP_DIR/checksum.txt" value=""
  if [[ -n "${TELECODE_SHA256:-}" ]]; then
    printf '%s' "$TELECODE_SHA256"
    return 0
  fi
  if curl -fsSL --connect-timeout 20 -o "$sidecar" \
      "https://github.com/${REPO_OWNER}/${REPO_NAME}/releases/download/${ref}/telecode-${ref}.tar.gz.sha256" \
      >>"$TMP_DIR/bootstrap.log" 2>&1 && [[ -s "$sidecar" ]]; then
    value="$(awk 'NR == 1 { print $1 }' "$sidecar")"
    if [[ -n "$value" ]]; then
      printf '%s' "$value"
      return 0
    fi
  fi
  case "$ref" in
    "$PINNED_REF")
      printf '%s' "$PINNED_SHA256"
      return 0
      ;;
  esac
  return 1
}

size_for_ref() {
  local ref="$1" url="$2"
  if [[ -n "${TELECODE_SIZE:-}" ]]; then
    if [[ "$TELECODE_SIZE" =~ ^[0-9]+$ ]] && (( TELECODE_SIZE > 0 )); then
      printf '%s' "$TELECODE_SIZE"
      return 0
    fi
    return 1
  fi
  case "$ref" in
    "$PINNED_REF")
      printf '%s' "$PINNED_SIZE"
      return 0
      ;;
  esac
  content_length "$url" || true
}

show_log_tail() {
  local log="$1"
  if [[ -s "$log" ]]; then
    printf '%s--- output ---%s\n' "$C_DIM" "$C_RESET" >&2
    tail -n 20 "$log" >&2 || true
    printf '%s--------------%s\n' "$C_DIM" "$C_RESET" >&2
  fi
}

bootstrap_main() {
  local ref="${TELECODE_REF:-$PINNED_REF}"
  local url expected actual total source archive log

  if (( BOOTSTRAP_FLAG )) && [[ -n "$COMMAND" ]]; then
    fail "--curl-bootstrap does not accept extra arguments."
    exit 2
  fi

  ensure_tmp
  log="$TMP_DIR/bootstrap.log"
  : > "$log"

  case "$ref" in
    main|master|HEAD|refs/heads/*)
      fail "Refusing to fetch unpinned ref '$ref'; use a release tag or a full commit id."
      exit 2
      ;;
  esac
  if [[ ! "$ref" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    fail "Invalid ref '$ref'; only letters, digits, dot, underscore and hyphen are allowed."
    exit 2
  fi

  if ! command -v curl >/dev/null 2>&1; then
    fail "curl is required for the one-line installer."
    exit 3
  fi
  if ! command -v tar >/dev/null 2>&1; then
    fail "tar is required for the one-line installer."
    exit 3
  fi

  if [[ "$ref" =~ ^[0-9a-fA-F]{7,40}$ ]]; then
    url="https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/${ref}"
  else
    url="https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/refs/tags/${ref}"
  fi

  logo
  title "TeleCode bootstrap ${VERSION} (${ref})"

  if ! expected="$(checksum_for_ref "$ref")"; then
    fail "No SHA-256 checksum is published for ref '$ref'."
    printf 'Set TELECODE_SHA256=<64-hex-digest> (and optionally TELECODE_SIZE=<bytes>) and retry.\n' >&2
    exit 2
  fi
  if [[ ! "$expected" =~ ^[0-9a-fA-F]{64}$ ]]; then
    fail "The checksum for ref '$ref' is not a valid SHA-256 digest."
    exit 2
  fi
  expected="$(printf '%s' "$expected" | tr 'A-F' 'a-f')"

  total="$(size_for_ref "$ref" "$url" || true)"
  if [[ -n "$total" && ! "$total" =~ ^[0-9]+$ ]]; then
    total=""
  fi

  archive="$TMP_DIR/telecode.tar.gz"
  note "Downloading ${REPO_OWNER}/${REPO_NAME} at ${ref}"
  if ! download_with_progress "$url" "$archive" "$total" "$log"; then
    fail "Download failed."
    show_log_tail "$log"
    exit 1
  fi

  if ! actual="$(sha256_file "$archive" 2>>"$log")"; then
    fail "No SHA-256 tool found (sha256sum, shasum, or openssl)."
    show_log_tail "$log"
    exit 3
  fi
  actual="$(printf '%s' "$actual" | tr 'A-F' 'a-f' | tr -d ' ')"
  if [[ "$actual" != "$expected" ]]; then
    fail "SHA-256 mismatch for ref '$ref'; the archive was not extracted."
    printf '  expected: %s\n  actual:   %s\n' "$expected" "$actual" >&2
    exit 1
  fi
  ok "SHA-256 verified"

  mkdir -p "$TMP_DIR/src"
  if ! tar -xzf "$archive" -C "$TMP_DIR/src" >>"$log" 2>&1; then
    fail "Failed to extract the verified archive."
    show_log_tail "$log"
    exit 1
  fi

  source=""
  for candidate in "$TMP_DIR"/src/*; do
    [[ -d "$candidate" ]] || continue
    if [[ -n "$source" ]]; then
      fail "Archive has an unexpected layout (more than one top-level directory)."
      exit 1
    fi
    source="$candidate"
  done
  if [[ -z "$source" || ! -f "$source/install.sh" || ! -f "$source/tg_bridge.py" ]]; then
    fail "Archive does not contain the expected TeleCode files."
    exit 1
  fi
  chmod 0755 "$source/install.sh" 2>/dev/null || true

  if ( : </dev/tty ) 2>/dev/null; then
    printf '\n'
    logo
    printf '\nStarting TeleCode setup...\n\n'
    local rc=0
    bash "$source/install.sh" </dev/tty || rc=$?
    exit "$rc"
  fi

  printf '\n'
  logo
  printf '\nStarting TeleCode setup...\n\n'
  local rc=0
  bash "$source/install.sh" || rc=$?
  exit "$rc"
}

# ------------------------------------------------------------------- flags --
while [[ $# -gt 0 ]]; do
  case "$1" in
    --verbose) VERBOSE=1 ;;
    --quiet) QUIET=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --version) printf 'TeleCode installer %s\n' "$VERSION"; exit 0 ;;
    "--curl-bootstrap") BOOTSTRAP_FLAG=1 ;;
    --help|-h) usage; exit 0 ;;
    --bootstrap|--update|--uninstall|--enable|--start|--status|--configure-cli|--browser-setup|--setup|setup|listen|status|help)
      [[ -z "$COMMAND" ]] || { fail "Only one command may be given."; exit 2; }
      COMMAND="$1"
      ;;
    get-id)
      [[ -z "$COMMAND" ]] || { fail "Only one command may be given."; exit 2; }
      COMMAND="get-id"
      shift
      GETID_ARGS=("$@")
      break
      ;;
    *)
      fail "Unknown option: $1"
      usage >&2
      exit 2
      ;;
  esac
  shift
done

# One-line mode: explicit flag, or detected when the script arrives on stdin
# (curl | bash) with no project files beside it.
BOOTSTRAP_MODE=0
if (( BOOTSTRAP_FLAG )); then
  BOOTSTRAP_MODE=1
elif [[ -z "$COMMAND" && $# -eq 0 && ! -t 0 ]]; then
  case "$0" in
    bash|sh|-bash|-sh|*/bash|*/sh) BOOTSTRAP_MODE=1 ;;
    *)
      if [[ ! -f "./tg_bridge.py" ]]; then
        BOOTSTRAP_MODE=1
      fi
      ;;
  esac
fi
if [[ "$BOOTSTRAP_MODE" == "1" ]]; then
  bootstrap_main
fi

APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/telegram-bridge"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/telegram-bridge"
BIN_DIR="${HOME}/.local/bin"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SOURCE_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)"
PYTHON="$(command -v python3 || true)"

same_dir() {
  local left right
  left="$(cd -- "$1" 2>/dev/null && pwd -P)" || return 1
  right="$(cd -- "$2" 2>/dev/null && pwd -P)" || return 1
  [[ "$left" == "$right" ]]
}

same_content() {
  local source="$1" destination="$2"
  if command -v cmp >/dev/null 2>&1; then
    cmp -s "$source" "$destination"
  else
    [[ "$(cksum < "$source")" == "$(cksum < "$destination")" ]]
  fi
}

install_file() {
  local relative="$1"
  local source="$SOURCE_DIR/$relative"
  local destination="$APP_DIR/$relative"
  if [[ -e "$destination" && "$source" -ef "$destination" ]]; then
    return 0
  fi
  if [[ -e "$destination" ]] && same_content "$source" "$destination"; then
    return 0
  fi
  CHANGED_FILES=$((CHANGED_FILES + 1))
  (( DRY_RUN )) && return 0
  mkdir -p "$(dirname -- "$destination")"
  install -m 0644 "$source" "$destination"
}

# shellcheck disable=SC2317  # invoked indirectly through run_step
check_installed_cli() {
  ( cd -- "$1" && exec "$2" ./telegram-bridge.py --help )
}

# Run one step quietly. Output is captured and only shown on failure.
run_step() {
  local label="$1" hint="$2"
  shift 2
  if (( DRY_RUN )); then
    dry "$label"
    return 0
  fi
  if (( VERBOSE )); then
    if "$@"; then
      ok "$label"
      return 0
    fi
    local rc=$?
    fail "$label"
    [[ -n "$hint" ]] && printf '  fix: %s\n' "$hint" >&2
    return "$rc"
  fi
  ensure_tmp
  local log rc
  log="$(mktemp "$TMP_DIR/step.XXXXXX")"
  register_temp "$log"
  if "$@" >"$log" 2>&1; then
    rm -f -- "$log"
    ok "$label"
    return 0
  fi
  rc=$?
  fail "$label"
  show_log_tail "$log"
  [[ -n "$hint" ]] && printf '  fix: %s\n' "$hint" >&2
  rm -f -- "$log"
  return "$rc"
}

# ---------------------------------------------------------------- install ---
logo
(( QUIET )) || printf 'TeleCode installer %s\n\n' "$VERSION"

if [[ "$COMMAND" == "--update" ]] && same_dir "$SOURCE_DIR" "$APP_DIR"; then
  fail "Run ./install.sh --update from a source checkout, not the installed copy."
  exit 2
fi

if [[ -z "$PYTHON" ]]; then
  fail "Python 3.11+ is required; no install changes made."
  printf '  fix: install python3 and re-run ./install.sh\n' >&2
  exit 3
fi
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  fail "Python 3.11+ is required; no install changes made."
  printf '  fix: upgrade python3 and re-run ./install.sh\n' >&2
  exit 3
fi
(( QUIET )) || ok "Checking Python 3.11+"

if (( DRY_RUN )); then
  dry "Preparing $APP_DIR, $CONFIG_DIR and $BIN_DIR"
else
  mkdir -p "$APP_DIR/adapters" "$APP_DIR/telegram_bridge" "$APP_DIR/config" "$CONFIG_DIR" "$BIN_DIR"
  (( QUIET )) || ok "Preparing install directories"
fi

INSTALL_FILES=(
  "tg_bridge.py"
  "tg_mcp.py"
  "install.sh"
  "adapters/base.py"
  "adapters/__init__.py"
  "adapters/opencode.py"
  "adapters/claude_code.py"
  "adapters/codex.py"
  "adapters/cursor.py"
  "telegram_bridge/__init__.py"
  "telegram_bridge/state.py"
  "telegram_bridge/ui.py"
  "telegram_bridge/util.py"
  "telegram_bridge/telegram.py"
  "telegram_bridge/agents.py"
  "telegram_bridge/pickers.py"
  "telegram_bridge/routing.py"
  "telegram_bridge/listener.py"
  "telegram_bridge/cli.py"
  "telegram-bridge.py"
  "telegram-bridge.service"
  "SKILL.md"
  "setup_cli.py"
  "setup_web.py"
  "service_manager.py"
  "get_telegram_id.py"
  ".env.example"
  "telegram_bridge/web/index.html"
  "telegram_bridge/web/app.css"
  "telegram_bridge/web/app.js"
)
for relative in "${INSTALL_FILES[@]}"; do
  [[ "$relative" == telegram_bridge/web/* && ! -f "$SOURCE_DIR/$relative" ]] && continue
  install_file "$relative"
done

if (( DRY_RUN )); then
  :
else
  mkdir -p "$CONFIG_DIR/files"
fi
for template in "$SOURCE_DIR"/config/*.example.json; do
  [[ -f "$template" ]] || continue
  install_file "config/$(basename -- "$template")"
done
if (( CHANGED_FILES == 0 )); then
  (( QUIET )) || ok "Runtime files already up to date"
elif (( DRY_RUN )); then
  dry "Would update ${CHANGED_FILES} runtime file(s)"
else
  (( QUIET )) || ok "Installing runtime files (${CHANGED_FILES} updated)"
fi

if (( DRY_RUN )); then
  dry "Checking installed CLI imports"
else
  ensure_tmp
  run_step "Checking installed CLI imports" \
    "reinstall after fixing the Python error above" \
    check_installed_cli "$APP_DIR" "$PYTHON"
fi

WRAPPER_TMP=""
if (( DRY_RUN )); then
  dry "Installing CLI wrapper at $BIN_DIR/telecode"
else
  WRAPPER_TMP="$(mktemp "$BIN_DIR/.telecode.XXXXXX")"
  register_temp "$WRAPPER_TMP"
  cat > "$WRAPPER_TMP" <<'EOF'
#!/usr/bin/env bash
APP_DIR="${TELECODE_APP_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/telegram-bridge}"
export TELECODE_APP_DIR="$APP_DIR"
export TELEGRAM_BRIDGE_HOME="${TELEGRAM_BRIDGE_HOME:-${XDG_CONFIG_HOME:-$HOME/.config}/telegram-bridge}"
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
  if [[ -f "$BIN_DIR/telecode" ]] && same_content "$WRAPPER_TMP" "$BIN_DIR/telecode"; then
    rm -f -- "$WRAPPER_TMP"
    (( QUIET )) || ok "CLI wrapper already up to date"
  else
    mv -f "$WRAPPER_TMP" "$BIN_DIR/telecode"
    chmod 0755 "$BIN_DIR/telecode"
    (( QUIET )) || ok "Installing CLI wrapper"
  fi
fi

if [[ ! -f "$CONFIG_DIR/telegram.env" ]]; then
  if (( DRY_RUN )); then
    dry "Creating private config $CONFIG_DIR/telegram.env (0600)"
  else
    install -m 0600 "$SOURCE_DIR/.env.example" "$CONFIG_DIR/telegram.env"
    (( QUIET )) || ok "Creating private config (0600)"
  fi
fi
(( DRY_RUN )) || chmod 0600 "$CONFIG_DIR/telegram.env"

case "$(uname -s 2>/dev/null || true)" in
  MINGW*|MSYS*|CYGWIN*)
    if command -v cygpath >/dev/null 2>&1 && (( ! DRY_RUN )); then
      TELEGRAM_BRIDGE_HOME="$(cygpath -w "$CONFIG_DIR")" \
        run_step "Securing config permissions" "check the Windows account ACL" \
        "$PYTHON" "$APP_DIR/service_manager.py" secure-config
    fi
    ;;
esac

if (( QUIET )); then
  :
elif (( DRY_RUN )); then
  cat <<EOF
Would install to: $APP_DIR
Private config: $CONFIG_DIR/telegram.env
CLI: $BIN_DIR/telecode
Skill: $APP_DIR/SKILL.md
EOF
else
  cat <<EOF
Installed to: $APP_DIR
Private config: $CONFIG_DIR/telegram.env
CLI: $BIN_DIR/telecode
Skill: $APP_DIR/SKILL.md
EOF
fi

if [[ "$COMMAND" == "--bootstrap" ]]; then
  exit 0
fi
if [[ "$COMMAND" == "--update" ]]; then
  echo "Updated installed files in $APP_DIR. Private configuration was preserved."
  exit 0
fi

if [[ "$COMMAND" == "--uninstall" ]]; then
  case "$(uname -s 2>/dev/null || true)" in
    MINGW*|MSYS*|CYGWIN*|Darwin)
      service_config="$CONFIG_DIR"
      service_app="$APP_DIR"
      if [[ "$(uname -s 2>/dev/null || true)" != Darwin ]] && command -v cygpath >/dev/null 2>&1; then
        service_config="$(cygpath -w "$CONFIG_DIR")"
        service_app="$(cygpath -w "$APP_DIR")"
      fi
      TELECODE_SERVICE_APP_DIR="$service_app" TELEGRAM_BRIDGE_HOME="$service_config" "$PYTHON" "$APP_DIR/service_manager.py" uninstall || exit $?
      ;;
    *)
      if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
        systemctl --user disable --now telegram-bridge.service >/dev/null 2>&1 || true
        rm -f "$UNIT_DIR/telegram-bridge.service"
        systemctl --user daemon-reload || true
      fi
      echo "Service removed if present. App at $APP_DIR and private config at $CONFIG_DIR are preserved."
      ;;
  esac
  exit 0
fi

if [[ "$COMMAND" == "--help" || "$COMMAND" == "help" ]]; then
  cat <<'EOF'
TeleCode guided setup and commands:
  telecode              open the Setup/Exit menu
  telecode setup        configure a CLI and collect Telegram credentials
  telecode get-id       detect your private chat ID through your own bot
  telecode status       show listener status
  telecode listen       run the listener in this terminal
  telecode help         show this help
  ./install.sh --uninstall  remove OS startup service; keep app and config

Automatic startup uses systemd on Linux, a LaunchAgent on macOS, or a per-user
Scheduled Task on Windows. When the OS service manager is unavailable (for
example, a headless runner), setup prints the foreground command instead.

Create a bot with @BotFather and keep its token private. For your numeric
account ID, message @Getmyid_bot, or choose automatic detection and send /start
to your own bot. Never send your bot token to an ID lookup bot.
EOF
  exit 0
fi

have_systemd_user() {
  command -v systemctl >/dev/null 2>&1 || return 1
  systemctl --user show-environment >/dev/null 2>&1
}

check_credentials() {
  if [[ ! -f "$CONFIG_DIR/telegram.env" ]] || \
     ! grep -Eq '^TG_BOT_TOKEN=[0-9]{5,}:[A-Za-z0-9_-]{20,}$' "$CONFIG_DIR/telegram.env" || \
      ! grep -Eq '^TG_CHAT_ID=-?[0-9]+$' "$CONFIG_DIR/telegram.env"; then
    fail "Set a valid TG_BOT_TOKEN (from @BotFather) and numeric TG_CHAT_ID in $CONFIG_DIR/telegram.env before enabling."
    return 1
  fi
}

check_service_paths() {
  if printf '%s' "$CONFIG_DIR$APP_DIR" | grep -q '[[:space:]|&\\%"]'; then
    fail 'Systemd setup does not support whitespace or |, &, backslash, %, double quote, or newline in XDG paths.'
    return 2
  fi
}

enable_user_service() {
  check_credentials || return 1
  case "$(uname -s 2>/dev/null || true)" in
    MINGW*|MSYS*|CYGWIN*)
      service_config="$CONFIG_DIR"
      service_app="$APP_DIR"
      if command -v cygpath >/dev/null 2>&1; then
        service_config="$(cygpath -w "$CONFIG_DIR")"
        service_app="$(cygpath -w "$APP_DIR")"
      fi
      TELECODE_SERVICE_APP_DIR="$service_app" TELEGRAM_BRIDGE_HOME="$service_config" "$PYTHON" "$APP_DIR/service_manager.py" install
      return $?
      ;;
  esac
  check_service_paths || return 2
  if ! have_systemd_user; then
    warn "systemd user services are not available in this environment."
    warn "No service was enabled. Start the listener with: telecode listen"
    warn "In containers, WSL, or systems without systemd, keep that process running under your own supervisor."
    return 3
  fi
  mkdir -p "$UNIT_DIR"
  local tmp_unit
  tmp_unit="$(mktemp "$UNIT_DIR/.telegram-bridge.service.XXXXXX")"
  sed -e "s|%h/.config/telegram-bridge|$(printf '%s' "$CONFIG_DIR" | sed 's/[&|\\]/\\&/g')|g" \
      -e "s|%h/.local/share/telegram-bridge|$(printf '%s' "$APP_DIR" | sed 's/[&|\\]/\\&/g')|g" \
      "$APP_DIR/telegram-bridge.service" > "$tmp_unit"
  chmod 0644 "$tmp_unit"
  mv -f "$tmp_unit" "$UNIT_DIR/telegram-bridge.service"
  systemctl --user daemon-reload
  systemctl --user enable --now telegram-bridge.service
  (( QUIET )) || ok "Enabling user startup service"
}

# Write one key atomically into the private env file. The whole file is
# rewritten through a 0600 temporary file in the same directory and renamed.
set_env_var() {
  local key="$1" value="$2"
  local file="$CONFIG_DIR/telegram.env" tmp line
  case "$key" in
    TG_BOT_TOKEN)
      [[ "$value" =~ ^[0-9]{5,}:[A-Za-z0-9_-]{20,}$ ]] || return 1
      ;;
    TG_CHAT_ID)
      [[ "$value" =~ ^-?[0-9]+$ ]] || return 1
      ;;
    *)
      return 1
      ;;
  esac
  mkdir -p "$CONFIG_DIR"
  if [[ ! -f "$file" ]]; then
    : > "$file"
    chmod 0600 "$file"
  fi
  tmp="$(mktemp "$CONFIG_DIR/.telegram.env.XXXXXX")"
  register_temp "$tmp"
  chmod 0600 "$tmp"
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      "$key="*) continue ;;
    esac
    printf '%s\n' "$line"
  done < "$file" > "$tmp"
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  chmod 0600 "$tmp"
  mv -f "$tmp" "$file"
  chmod 0600 "$file"
}

mask_token() {
  local token="$1" account="${1%%:*}" secret="${1#*:}" tail
  tail="$(printf '%s' "$secret" | tail -c 4)"
  if [[ "$UI_TTY" == "1" ]]; then
    printf '%s••••••%s' "$account" "$tail"
  else
    printf '%s******%s' "$account" "$tail"
  fi
}

# Read without echoing. SECRET_INPUT receives the value; it is never printed.
read_secret() {
  local prompt="$1"
  SECRET_INPUT=""
  printf '%s%s%s ' "$C_BOLD" "$prompt" "$C_RESET"
  if [[ -t 0 ]]; then
    IFS= read -r -s SECRET_INPUT || return 1
  else
    IFS= read -r SECRET_INPUT || return 1
  fi
  printf '\n'
}

prompt_token() {
  local token attempt
  attempt=0
  while (( attempt < 3 )); do
    attempt=$((attempt + 1))
    if ! read_secret "Telegram bot token (from @BotFather): "; then
      fail "No token was entered."
      return 1
    fi
    token="${SECRET_INPUT//$'\r'/}"
    if [[ "$token" =~ ^[0-9]{5,}:[A-Za-z0-9_-]{20,}$ ]]; then
      TOKEN_VALUE="$token"
      ok "Token accepted: $(mask_token "$token")"
      return 0
    fi
    warn "Invalid token format (expected 12345:ABC…). Attempt ${attempt} of 3."
  done
  fail "Token was not accepted after 3 attempts; nothing was saved."
  return 1
}

prompt_chat_id() {
  local chat attempt
  attempt=0
  while (( attempt < 3 )); do
    attempt=$((attempt + 1))
    printf '%s%s%s ' "$C_BOLD" "Numeric owner chat ID (or A for automatic detection):" "$C_RESET"
    IFS= read -r chat || { fail "No chat ID was entered."; return 1; }
    chat="${chat//$'\r'/}"
    if [[ "$chat" =~ ^-?[0-9]+$ ]]; then
      CHAT_VALUE="$chat"
      ok "Chat ID accepted: $chat"
      return 0
    fi
    if [[ "$chat" =~ ^[Aa]$ ]]; then
      TELEGRAM_BRIDGE_HOME="$CONFIG_DIR" "$PYTHON" "$APP_DIR/get_telegram_id.py" --configure
      return 0
    fi
    warn "Enter a numeric chat ID or A. Attempt ${attempt} of 3."
  done
  fail "Chat ID was not accepted after 3 attempts; nothing was saved."
  return 1
}

if [[ "$COMMAND" == "--enable" ]]; then
  enable_user_service || exit $?
  exit 0
fi

if [[ "$COMMAND" == "--start" || "$COMMAND" == "listen" ]]; then
  TELEGRAM_BRIDGE_HOME="$CONFIG_DIR" exec "$PYTHON" "$APP_DIR/telegram-bridge.py" listen
fi

if [[ "$COMMAND" == "--status" || "$COMMAND" == "status" ]]; then
  TELEGRAM_BRIDGE_HOME="$CONFIG_DIR" exec "$PYTHON" "$APP_DIR/telegram-bridge.py" status
fi

if [[ "$COMMAND" == "--configure-cli" ]]; then
  TELEGRAM_BRIDGE_APP_DIR="$APP_DIR" "$PYTHON" "$APP_DIR/setup_cli.py"
  exit $?
fi

if [[ "$COMMAND" == "--browser-setup" || "$COMMAND" == "--web" ]]; then
  TELEGRAM_BRIDGE_APP_DIR="$APP_DIR" TELEGRAM_BRIDGE_HOME="$CONFIG_DIR" \
    exec "$PYTHON" "$APP_DIR/setup_web.py"
fi

if [[ "$COMMAND" == "--cli" ]]; then
  TELEGRAM_BRIDGE_APP_DIR="$APP_DIR" "$PYTHON" "$APP_DIR/setup_cli.py"
  exit $?
fi

if [[ "$COMMAND" == "get-id" ]]; then
  exec "$PYTHON" "$APP_DIR/get_telegram_id.py" "${GETID_ARGS[@]+"${GETID_ARGS[@]}"}"
fi

if [[ -z "$COMMAND" || "$COMMAND" == "--setup" || "$COMMAND" == "setup" ]]; then
  if (( DRY_RUN )); then
    note "Dry run complete; no files were changed."
    exit 0
  fi
  if (( ASSUME_YES )); then
    if check_credentials; then
      enable_user_service || true
      (( QUIET )) || ok "Non-interactive setup complete"
      exit 0
    fi
    warn "Credentials are missing; skipped interactive setup and startup service."
    warn "Run: telecode setup"
    exit 0
  fi
  if [[ ! -t 0 ]]; then
    fail "Interactive setup requires a terminal. Rerun install.sh in a terminal, or use --yes."
    exit 2
  fi
  printf 'Setup: Browser (recommended) / Terminal [B/t]: '
  IFS= read -r setup_choice || { fail "Setup choice was not received."; exit 130; }
  case "${setup_choice,,}" in
    ""|b|browser|web)
      TELEGRAM_BRIDGE_APP_DIR="$APP_DIR" TELEGRAM_BRIDGE_HOME="$CONFIG_DIR" \
        exec "$PYTHON" "$APP_DIR/setup_web.py"
      ;;
    t|terminal|cli) ;;
    *) fail "Choose Browser or Terminal."; exit 2 ;;
  esac
  TELEGRAM_BRIDGE_APP_DIR="$APP_DIR" "$PYTHON" "$APP_DIR/setup_cli.py" || {
    fail "CLI integration was cancelled or could not be configured; listener was not enabled."
    exit 2
  }
  if ! grep -Eq '^TG_BOT_TOKEN=[0-9]{5,}:[A-Za-z0-9_-]{20,}$' "$CONFIG_DIR/telegram.env"; then
    title "Telegram bot token"
    prompt_token || exit 2
    set_env_var TG_BOT_TOKEN "$TOKEN_VALUE" || { fail "Could not save the bot token."; exit 1; }
  fi
  if ! grep -Eq '^TG_CHAT_ID=-?[0-9]+$' "$CONFIG_DIR/telegram.env"; then
    title "Owner chat ID"
    note "To find your ID, message @Getmyid_bot and enter it below; or choose auto-detection."
    prompt_chat_id || exit 2
    if [[ -n "${CHAT_VALUE:-}" ]]; then
      set_env_var TG_CHAT_ID "$CHAT_VALUE" || { fail "Could not save the chat ID."; exit 1; }
    fi
  fi
  if ! grep -Eq '^TG_CHAT_ID=-?[0-9]+$' "$CONFIG_DIR/telegram.env"; then
    fail "Owner chat ID was not saved; listener will not be enabled."
    exit 2
  fi
  if have_systemd_user; then
    enable_user_service || exit $?
    ok "Setup complete: MCP configured and TeleCode enabled at login."
    note "Next: restart your coding-agent CLI, then run: telecode status"
  else
    ok "Setup complete: MCP configured and credentials saved."
    warn "systemd user services are not available here, so automatic startup was skipped."
    note "Next: telecode listen   (keep it running), then telecode status"
  fi
  exit 0
fi

fail "Unknown command: $COMMAND"
usage >&2
exit 2
