#!/usr/bin/env python3
"""Interactive, backup-first MCP setup for installed coding-agent CLIs."""
import json
import os
import pathlib
import shutil
import tempfile
import time
import tomllib
import unicodedata
import sys


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


def choose(options):
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            import termios
            import tty
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            selected = 0
            color = sys.platform != "win32" and "NO_COLOR" not in os.environ
            print("\nSelect the coding-agent CLI to configure (↑/↓, Enter; q to cancel):", flush=True)
            lines = []
            for host in options:
                found, config, supported = discover(host)
                suffix = "detected" if found or config else "manual setup"
                if not supported:
                    suffix += "; manual config"
                lines.append(f"  {host[0]} ({suffix})")
            print("\n".join(lines), flush=True)
            for _ in lines:
                sys.stdout.write("\033[1A")
            sys.stdout.flush()
            try:
                tty.setraw(fd)
                while True:
                    sys.stdout.write("\033[1A" * len(lines))
                    for i, line in enumerate(lines):
                        if i == selected:
                            marker = "\033[1;38;2;48;179;239m❯\033[0m " if color else "❯ "
                            label = f"\033[1;38;2;48;179;239m{line.strip()}\033[0m" if color else line.strip()
                        else:
                            marker, label = "  ", line.strip()
                        sys.stdout.write("\033[2K" + marker + label + "\n")
                    sys.stdout.flush()
                    key = sys.stdin.read(1)
                    if key == "\x1b":
                        seq = sys.stdin.read(2)
                        if seq == "[A": selected = (selected - 1) % len(options)
                        elif seq == "[B": selected = (selected + 1) % len(options)
                    elif key in ("\r", "\n"):
                        return options[selected]
                    elif key.lower() == "q":
                        return None
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except (ImportError, OSError, AttributeError):
            pass
    print("\nSelect the coding-agent CLI to configure:")
    color = sys.stdout.isatty() and sys.platform != "win32" and "NO_COLOR" not in os.environ
    for i, host in enumerate(options, 1):
        found, config, supported = discover(host)
        suffix = "detected" if found or config else "manual setup"
        if not supported:
            suffix += "; manual config"
        mark = "●" if i == 1 else "○"
        line = f"  {mark} {host[0]} ({suffix})"
        if color and i == 1:
            line = f"\033[1;38;2;48;179;239m{line}\033[0m"
        print(line)
    while True:
        answer = input("Enter a listed number (or q to cancel): ").strip().lower()
        if answer in ("q", "quit", "skip"):
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        print("Choose one of the listed numbers.")


def backup(path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(path.name + f".telegram-bridge.bak.{stamp}.{os.getpid()}")
    shutil.copy2(path, dest)
    return dest


def atomic_write(path, contents):
    old_mode = (path.stat().st_mode & 0o777) if path.exists() else 0o600
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = pathlib.Path(temp_name)
    try:
        os.fchmod(fd, old_mode)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
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


def main():
    options = selectable_hosts()
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
            choice = input("Enter number: ").strip()
            if not choice.isdigit() or not 1 <= int(choice) <= len(candidates):
                print("Cancelled; no files changed.")
                return 2
            config = candidates[int(choice) - 1]
    if host[1] == "codex" and supported and config and config.suffix == ".toml":
        try:
            new_content = register_codex_toml(config)
        except ValueError as e:
            print(f"Cannot configure Codex: {e}; no files changed.")
            return 2
        print(f"Target: {config}")
        confirm = input("Back up and add Telegram Bridge to this config? [y/N] ").strip().lower()
        if confirm != "y":
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
        confirm = input("Create Codex MCP config? [y/N] ").strip().lower()
        if confirm != "y":
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
    confirm = input("Back up and add Telegram Bridge to this config? [y/N] ").strip().lower()
    if confirm != "y":
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
