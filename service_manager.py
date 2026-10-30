"""Install and remove TeleCode's per-user login service on Windows and macOS."""
import os
import pathlib
import plistlib
import re
import subprocess
import sys
import tempfile


TASK_NAME = os.environ.get("TELECODE_TASK_NAME", "TeleCode Telegram Bridge")
PLIST_NAME = "org.telecode.telegram-bridge.plist"


def _config_dir():
    return pathlib.Path(os.environ.get("TELEGRAM_BRIDGE_HOME") or pathlib.Path.home() / ".config" / "telegram-bridge").expanduser()


def _app_dir():
    return pathlib.Path(os.environ.get("TELECODE_SERVICE_APP_DIR") or pathlib.Path(__file__).resolve().parent).expanduser().resolve()


def _check_credentials():
    env_file = _config_dir() / "telegram.env"
    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Missing credentials file: {env_file}") from exc
    if not re.search(r"^TG_BOT_TOKEN=[0-9]{5,}:[A-Za-z0-9_-]{20,}\r?$", text, re.M):
        raise RuntimeError(f"Set a valid dummy or real TG_BOT_TOKEN in {env_file} before installing the service.")
    if not re.search(r"^TG_CHAT_ID=-?[0-9]+\r?$", text, re.M):
        raise RuntimeError(f"Set a numeric TG_CHAT_ID in {env_file} before installing the service.")


def secure_config(path=None):
    """Set owner-only access to a Windows secrets file; no inherited ACLs."""
    if os.name != "nt":
        return
    path = pathlib.Path(path or (_config_dir() / "telegram.env")).resolve()
    _set_windows_private_acl(path)


def _set_windows_private_acl(path):
    identity = subprocess.run(["whoami"], capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{identity}:(F)"],
                   capture_output=True, text=True, check=True)


def _mac_plist_path():
    override = os.environ.get("TELECODE_LAUNCH_AGENT_PATH")
    if override:
        return pathlib.Path(override).expanduser()
    return pathlib.Path.home() / "Library" / "LaunchAgents" / PLIST_NAME


def generate_macos_plist():
    app = _app_dir()
    config = _config_dir().resolve()
    python = pathlib.Path(sys.executable).resolve()
    logs = config / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": "org.telecode.telegram-bridge",
        "ProgramArguments": [str(python), str(app / "telegram-bridge.py"), "listen"],
        "WorkingDirectory": str(app),
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": {"TELEGRAM_BRIDGE_HOME": str(config), "TELECODE_APP_DIR": str(app)},
        "StandardOutPath": str(logs / "listener.out.log"),
        "StandardErrorPath": str(logs / "listener.err.log"),
    }
    destination = _mac_plist_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{PLIST_NAME}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            plistlib.dump(payload, stream, fmt=plistlib.FMT_XML, sort_keys=True)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return destination


def _install_windows():
    _check_credentials()
    python = pathlib.Path(sys.executable).resolve()
    script = _app_dir() / "telegram-bridge.py"
    # The wrapper carries the runtime directory into the logon task environment.
    wrapper = _config_dir() / "telecode-listener.cmd"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    def batch_quote(value):
        return str(value).replace("%", "%%")
    wrapper.write_text(
        "@echo off\r\n"
        f'set "TELEGRAM_BRIDGE_HOME={batch_quote(_config_dir())}"\r\n'
        f'set "TELECODE_APP_DIR={batch_quote(_app_dir())}"\r\n'
        f'"{batch_quote(python)}" "{batch_quote(script)}" listen\r\n',
        encoding="utf-8",
    )
    _set_windows_private_acl(wrapper)
    # schtasks accepts a single /TR string. Run the generated environment wrapper.
    command = f'cmd.exe /d /c ""{wrapper}""'
    subprocess.run(["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", TASK_NAME,
                    "/TR", command, "/RL", "LIMITED"], check=True)
    print(f"Installed per-user logon task: {TASK_NAME}")


def _uninstall_windows():
    query = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME],
                           capture_output=True, text=True, check=False)
    if query.returncode == 0:
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME], check=True)
    (_config_dir() / "telecode-listener.cmd").unlink(missing_ok=True)
    print(f"Removed per-user logon task if present: {TASK_NAME}")


def _install_macos():
    _check_credentials()
    plist = generate_macos_plist()
    subprocess.run(["plutil", "-lint", str(plist)], capture_output=True, text=True, check=True)
    uid = os.getuid()
    # Make repeated install/update calls idempotent; there may already be a
    # loaded agent using the same label and a previous plist configuration.
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/org.telecode.telegram-bridge"],
                   capture_output=True, text=True, check=False)
    result = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        print("Warning: LaunchAgent plist is valid, but launchctl bootstrap failed; this is common on headless systems.", file=sys.stderr)
        detail = (result.stderr or result.stdout).strip()
        if detail:
            print(detail, file=sys.stderr)
    else:
        print(f"Loaded per-user LaunchAgent: {plist}")


def _uninstall_macos():
    plist = _mac_plist_path()
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)],
                   capture_output=True, text=True, check=False)
    plist.unlink(missing_ok=True)
    print(f"Removed LaunchAgent if present: {plist}")


def install():
    if os.name == "nt":
        _install_windows()
    elif sys.platform == "darwin":
        _install_macos()
    else:
        raise RuntimeError("service_manager.py supports Windows and macOS; use systemd on Linux.")


def uninstall():
    if os.name == "nt":
        _uninstall_windows()
    elif sys.platform == "darwin":
        _uninstall_macos()
    else:
        raise RuntimeError("service_manager.py supports Windows and macOS; use systemd on Linux.")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv == ["install"]:
            install()
        elif argv == ["uninstall"]:
            uninstall()
        elif argv == ["generate-macos-plist"] and sys.platform == "darwin":
            print(generate_macos_plist())
        elif argv == ["secure-config"]:
            secure_config()
        else:
            print("Usage: service_manager.py {install|uninstall|generate-macos-plist|secure-config}", file=sys.stderr)
            return 2
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        print(f"Service operation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
