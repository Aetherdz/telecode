#!/usr/bin/env python3
"""Interactive, backup-first MCP setup for installed coding-agent CLIs."""
import json
import os
import pathlib
import re
import shutil
import tempfile
import time
import tomllib
import unicodedata
import sys

from telegram_bridge import ui


HOME = pathlib.Path.home()
_APP_OVERRIDE = os.environ.get("TELEGRAM_BRIDGE_APP_DIR")
APP = pathlib.Path(_APP_OVERRIDE).resolve() if _APP_OVERRIDE else pathlib.Path(__file__).resolve().parent
if _APP_OVERRIDE and (not APP.is_dir() or not (APP / "tg_mcp.py").is_file()):
    raise SystemExit("TELEGRAM_BRIDGE_APP_DIR must point to an installed TeleCode directory.")
_PYTHON_OVERRIDE = os.environ.get("TELEGRAM_BRIDGE_PYTHON")
if _PYTHON_OVERRIDE and not pathlib.Path(_PYTHON_OVERRIDE).is_absolute():
    raise SystemExit("TELEGRAM_BRIDGE_PYTHON must be an absolute executable path.")
if _PYTHON_OVERRIDE and not os.access(_PYTHON_OVERRIDE, os.X_OK):
    raise SystemExit("TELEGRAM_BRIDGE_PYTHON must point to an executable interpreter.")
MCP_COMMAND = [_PYTHON_OVERRIDE or sys.executable, str(APP / "tg_mcp.py")]
XDG_CONFIG = pathlib.Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
XDG_DATA = pathlib.Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share"))
RUNTIME_CONFIG = XDG_CONFIG / "telegram-bridge"
APP_DIR = XDG_DATA / "telegram-bridge"

HOSTS = [
    ("OpenCode", "opencode", [XDG_CONFIG / "opencode/opencode.json"], True),
    ("Claude Code", "claude", [HOME / ".claude.json", HOME / ".claude/settings.json"], True),
    ("Codex CLI", "codex", [HOME / ".codex/config.toml"], True),
    ("Cursor", "cursor", [HOME / ".cursor/mcp.json"], True),
    ("Gemini CLI", "gemini", [HOME / ".gemini/settings.json"], True),
    ("Aider", "aider", [HOME / ".aider.conf.yml"], False),
    ("Cline", "cline", [HOME / ".vscode/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"], True),
    ("Continue", "continue", [HOME / ".continue/config.json", HOME / ".continue/config.yaml"], False),
    ("Roo Code", "roo", [HOME / ".vscode/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json"], True),
    ("Amazon Q Developer", "q", [HOME / ".aws/amazonq/mcp.json"], True),
    ("Other MCP client", None, [], False),
]

MCP_EXAMPLES = {
    "opencode": "config/opencode.example.json",
    "claude": "config/claude-code.example.json",
    "gemini": "config/gemini-cli.example.json",
    "cline": "config/cline.example.json",
    "roo": "config/roo-code.example.json",
    "q": "config/amazon-q.example.json",
    "cursor": "config/cursor.example.json",
}


def discover(host):
    label, executable, configs, supported = host
    found_cli = bool(executable and shutil.which(executable))
    found_config = next((p for p in configs if p.is_file() and os.access(p, os.R_OK)), None)
    return found_cli, found_config, supported


def selectable_hosts():
    detected = []
    for host in HOSTS:
        if host[1] is None:
            continue
        found_cli, found_config, supported = discover(host)
        if found_cli or found_config:
            detected.append(host)
    # Always allow explicit manual config as a final choice.
    detected.append(HOSTS[-1])
    return detected


def _color_enabled():
    return ui.supports_color()


def _paint(text, code):
    return ui.paint(text, code)


def _accent(text):
    return ui.accent(text)


def _dim(text):
    return ui.dim(text)


def _green(text):
    return ui.green(text)


def _yellow(text):
    return ui.yellow(text)


def host_state(host):
    """Human-readable detection state used by both menu styles."""
    _, executable, _, supported = host
    if executable is None:
        return "manual setup", "dim"
    found_cli, found_config, _ = discover(host)
    if found_cli and found_config:
        state, tone = "CLI + config found", "ok"
    elif found_cli:
        state, tone = "CLI found", "ok"
    elif found_config:
        state, tone = "config found", "warn"
    else:
        state, tone = "not detected", "dim"
    if not supported:
        state += " - manual config"
        tone = "warn"
    return state, tone


def _state_text(state, tone):
    if tone == "ok":
        return _green(state)
    if tone == "warn":
        return _yellow(state)
    return _dim(state)


def _menu_rows(options):
    labels = [f"{index}. {host[0]}" for index, host in enumerate(options, 1)]
    states = [host_state(host) for host in options]
    label_width = max(_columns(label) for label in labels)
    state_width = max(_columns(state) for state, _ in states)
    return labels, states, label_width, state_width


def _box(title, rows, width):
    inner = width - 2
    heading = f"\u2500 {title} "
    top = "\u250c" + heading + "\u2500" * max(0, inner - len(heading)) + "\u2510"
    body = ["\u2502" + _pad_display(row, inner) + "\u2502" for row in rows]
    bottom = "\u2514" + "\u2500" * inner + "\u2518"
    return [_dim(top)] + body + [_dim(bottom)]


def _columns(text):
    """Approximate terminal display width without counting ANSI escapes."""
    plain = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    width = 0
    for index, char in enumerate(plain):
        if unicodedata.combining(char):
            continue
        if char == "\u200d" or (index and plain[index - 1] == "\u200d"):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def _pad_display(text, width):
    return text + " " * max(0, width - _columns(text))


def _menu_lines(options, selected):
    labels, states, label_width, state_width = _menu_rows(options)
    rows = []
    for index, (label, (state, tone)) in enumerate(zip(labels, states)):
        padded_label = _pad_display(label, label_width)
        padded_state = _pad_display(state, state_width)
        if index == selected:
            rows.append(_accent(_pad_display("\u276f " + label, label_width + 2)
                                + "  " + padded_state + " "))
        else:
            rows.append("  " + padded_label
                        + "  " + _state_text(padded_state, tone) + " ")
    title = "Select the coding-agent CLI to configure"
    width = max(label_width + state_width + 8, _columns(title) + 6)
    lines = _box(title, rows, width)
    lines.append(_dim("\u2191/\u2193 move \u00b7 1-9 jump \u00b7 Enter select \u00b7 q cancel"))
    return lines


def _write_lines(lines):
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()


def _redraw(lines):
    sys.stdout.write(f"\033[{len(lines)}A")
    for line in lines:
        sys.stdout.write("\r\033[2K" + line + "\n")
    sys.stdout.flush()


def _choose_numbered(options):
    labels, states, label_width, state_width = _menu_rows(options)
    print()
    print(_accent("Select the coding-agent CLI to configure"))
    print(_dim("-" * (label_width + state_width + 6)))
    for label, (state, tone) in zip(labels, states):
        row = "  " + _pad_display(label, label_width) + "  " + _state_text(_pad_display(state, state_width), tone)
        print(row.rstrip())
    print(_dim("-" * (label_width + state_width + 6)))
    while True:
        try:
            answer = input("Enter a number (or q to cancel): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if answer in ("q", "quit", "skip"):
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        print("Choose one of the listed numbers.")


def ask(prompt):
    """input() that treats EOF and Ctrl-C as a clean cancellation."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def _choose_arrow(options):
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    selected = 0
    lines = _menu_lines(options, selected)
    try:
        tty.setraw(fd)
        sys.stdout.write("\033[?25l")
        _write_lines(lines)
        while True:
            key = sys.stdin.read(1)
            if key == "\x1b":
                # Arrow keys arrive as one escape sequence in a single read burst.
                seq = sys.stdin.read(2)
                if seq == "[A":
                    selected = (selected - 1) % len(options)
                elif seq == "[B":
                    selected = (selected + 1) % len(options)
                else:
                    _redraw(_menu_lines(options, None))
                    return None
            elif key in ("\r", "\n"):
                _redraw(lines)
                print(_green("Selected: ") + options[selected][0])
                return options[selected]
            elif key in ("q", "Q", "\x03", "\x04"):
                _redraw(_menu_lines(options, None))
                return None
            elif key.isdigit() and 1 <= int(key) <= len(options):
                selected = int(key) - 1
                lines = _menu_lines(options, selected)
                _redraw(lines)
                print(_green("Selected: ") + options[selected][0])
                return options[selected]
            lines = _menu_lines(options, selected)
            _redraw(lines)
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def choose(options):
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            return _choose_arrow(options)
        except (ImportError, OSError, AttributeError, ValueError):
            pass
    return _choose_numbered(options)


def backup(path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(path.name + f".telegram-bridge.bak.{stamp}.{os.getpid()}")
    shutil.copy2(path, dest)
    return dest


def atomic_write(path, contents, mode=None):
    old_mode = mode if mode is not None else ((path.stat().st_mode & 0o777) if path.exists() else 0o600)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = pathlib.Path(temp_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, old_mode)
        stream = os.fdopen(fd, "w", encoding="utf-8")
        fd = None  # fdopen now owns and closes the descriptor on all paths.
        with stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # Some platforms/filesystems cannot open or sync directory entries.
            # File content is already fsynced and the replacement has succeeded.
            pass
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        temp.unlink(missing_ok=True)
        raise


def validate_wordmark(rows):
    """Check half-block art stays aligned in terminal display columns."""
    if not 1 <= len(rows) <= 16:
        raise ValueError("wordmark must contain between 1 and 16 rows")
    alphabet = set("█▀▄ ")
    for row in rows:
        if set(row) - alphabet:
            raise ValueError("wordmark contains unsupported glyphs")
    widths = []
    for row in rows:
        width = sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in row)
        widths.append(width)
    if len(set(widths)) != 1:
        raise ValueError(f"wordmark rows have inconsistent display widths: {widths}")
    return widths[0]


# Exact half-block transcription of the approved pixel-grid wordmark:
# 5x7 pixel cells per letter, one empty pixel column between letters.
APPROVED_WORDMARK = (
    "▀▀█▀▀ █▀▀▀▀ █     █▀▀▀▀ ▄▀▀▀▀ ▄▀▀▀▄ █▀▀▀▄ █▀▀▀▀",
    "  █   █▄▄▄  █     █▄▄▄  █     █   █ █   █ █▄▄▄ ",
    "  █   █     █     █     █     █   █ █   █ █    ",
    "  ▀   ▀▀▀▀▀ ▀▀▀▀▀ ▀▀▀▀▀  ▀▀▀▀  ▀▀▀  ▀▀▀▀  ▀▀▀▀▀",
)
APPROVED_WORDMARK_WIDTH = validate_wordmark(APPROVED_WORDMARK)


def register_json(path, host):
    data = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("config root must be a JSON object")
    entry = {"command": MCP_COMMAND[0], "args": MCP_COMMAND[1:],
             "env": {"TELEGRAM_BRIDGE_HOME": str(RUNTIME_CONFIG)}}
    kind = host[1]
    if kind == "opencode":
        mcp = data.setdefault("mcp", {})
        if not isinstance(mcp, dict):
            raise ValueError("OpenCode mcp config must be an object")
        servers = mcp.setdefault("servers", {})
        if not isinstance(servers, dict):
            raise ValueError("OpenCode mcp.servers must be an object")
        if "telegram-bridge" in servers:
            raise ValueError("telegram-bridge already configured; refusing overwrite")
        servers["telegram-bridge"] = {"type": "local", "command": MCP_COMMAND,
                                      "environment": entry["env"]}
    elif kind == "claude":
        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict) or "telegram-bridge" in servers:
            raise ValueError("invalid or existing mcpServers.telegram-bridge; refusing overwrite")
        servers["telegram-bridge"] = {"type": "stdio", **entry}
    elif kind == "gemini":
        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict) or "telegram-bridge" in servers:
            raise ValueError("invalid or existing mcpServers.telegram-bridge; refusing overwrite")
        servers["telegram-bridge"] = entry
    elif kind in ("cline", "roo", "q", "cursor"):
        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict) or "telegram-bridge" in servers:
            raise ValueError("invalid or existing mcpServers.telegram-bridge; refusing overwrite")
        servers["telegram-bridge"] = entry
    elif kind == "codex":
        raise ValueError("Codex requires TOML configuration")
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def register_codex_toml(path):
    """Append Codex MCP config conservatively; refuse unsupported TOML shapes."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        parsed = tomllib.loads(existing)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError("Codex config TOML is invalid; left unchanged") from exc
    servers = parsed.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ValueError("Codex mcp_servers must be a table; left unchanged")
    if "telegram-bridge" in servers:
        raise ValueError("telegram-bridge is already configured; left unchanged")
    prefix = "\n" if existing and not existing.endswith("\n") else ""
    block = f'''{prefix}\n[mcp_servers.telegram-bridge]
command = {json.dumps(MCP_COMMAND[0])}
args = {json.dumps(MCP_COMMAND[1:])}

[mcp_servers.telegram-bridge.env]
TELEGRAM_BRIDGE_HOME = {json.dumps(str(RUNTIME_CONFIG))}
'''
    return existing.rstrip() + "\n" + block


def register_for_web(cli, config_path=None):
    """Return the canonical config destination and proposed content for the wizard.

    The browser never chooses a destination path. Only known client IDs and
    repository-defined paths are accepted; callers must display/confirm before
    writing and use backup() plus atomic_write().
    """
    host = next((item for item in HOSTS if item[1] == cli), None)
    if host is None or not host[3]:
        raise ValueError("Choose a supported coding CLI.")
    _, detected_config, supported = discover(host)
    config = detected_config or host[2][0]
    if cli == "claude" and config_path is not None:
        if config_path not in host[2]:
            raise ValueError("Unsupported Claude config scope.")
        config = config_path
    if config.suffix == ".toml":
        content = register_codex_toml(config)
    elif config.suffix == ".json":
        content = register_json(config, host)
    else:
        raise ValueError("Automatic config editing is unavailable for this client.")
    return config, content


def main():
    options = selectable_hosts()
    if not options:
        print("No coding-agent CLI integrations are available.")
        return 2
    if len(options) == 1 and options[0][1] is None:
        print("No supported coding-agent CLI detected.")
        options = HOSTS
    host = choose(options)
    if not host:
        print("Skipped CLI integration. See docs/INSTALL.md for manual setup.")
        return 2
    _, config, supported = discover(host)
    if host[1] is None:
        print("Manual MCP setup selected; no config files changed.")
        print(f"Command: {MCP_COMMAND[0]} {' '.join(MCP_COMMAND[1:])}")
        print(f"Runtime: {HOME / '.config/telegram-bridge'}")
        return 0
    if host[1] == "claude" and supported:
        candidates = [p for p in host[2] if p.parent.exists()]
        if len(candidates) > 1:
            print("Choose Claude Code config scope:")
            for idx, path in enumerate(candidates, 1):
                print(f"  {idx}. {path}")
            choice = ask("Enter number: ")
            if choice is None or not choice.strip().isdigit() or \
                    not 1 <= int(choice.strip()) <= len(candidates):
                print("Cancelled; no files changed.")
                return 2
            config = candidates[int(choice.strip()) - 1]
    if host[1] == "codex" and supported and config and config.suffix == ".toml":
        try:
            new_content = register_codex_toml(config)
        except ValueError as e:
            print(f"Cannot configure Codex: {e}; no files changed.")
            return 2
        print(f"Target: {config}")
        confirm = ask("Back up and add Telegram Bridge to this config? [y/N] ")
        if confirm is None or confirm.strip().lower() != "y":
            print("Cancelled; no files changed.")
            return 2
        if config.exists():
            print(f"Backup: {backup(config)}")
        atomic_write(config, new_content)
        print(f"Configured Codex CLI MCP integration at {config}")
        return 0
    if host[1] == "codex" and supported and not config:
        config = HOME / ".codex/config.toml"
        try:
            new_content = register_codex_toml(config)
        except ValueError as e:
            print(f"Cannot configure Codex: {e}; no files changed.")
            return 2
        print(f"Target: {config}")
        confirm = ask("Create Codex MCP config? [y/N] ")
        if confirm is None or confirm.strip().lower() != "y":
            print("Cancelled; no files changed.")
            return 2
        config.parent.mkdir(parents=True, exist_ok=True)
        if config.exists():
            print(f"Backup: {backup(config)}")
        atomic_write(config, new_content)
        print(f"Configured Codex CLI MCP integration at {config}")
        return 0
    if not supported or (not config and host[1] not in ("opencode", "claude", "gemini", "cursor", "cline", "roo", "q")) or (config and config.suffix != ".json"):
        print(f"Automatic config edit is not supported for {host[0]} on this installation.")
        example = MCP_EXAMPLES.get(host[1])
        if example:
            print(f"No files changed. Use {APP / example} for a manual setup.")
        else:
            print("No files changed. See docs/INSTALL.md for manual MCP setup.")
        return 2
    if config is None:
        config = host[2][0]
    try:
        contents = register_json(config, host)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"Cannot configure {host[0]}: {e}; no files changed.")
        return 2
    print(f"Target: {config}")
    print(f"MCP server command: {MCP_COMMAND[0]} {' '.join(MCP_COMMAND[1:])}")
    confirm = ask("Back up and add Telegram Bridge to this config? [y/N] ")
    if confirm is None or confirm.strip().lower() != "y":
        print("Cancelled; no files changed.")
        return 2
    config.parent.mkdir(parents=True, exist_ok=True)
    if config.exists():
        saved = backup(config)
        print(f"Backup: {saved}")
    atomic_write(config, contents)
    print(f"Configured {host[0]} MCP integration at {config}")
    print("Restart the CLI to load the Telegram Bridge MCP server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
