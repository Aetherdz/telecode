"""TeleCode Telegram bridge package.

The package root is the single home for shared mutable bridge state. Every
submodule reads and writes bridge symbols through `import telegram_bridge as tg`
at call time, so patching the root (or the tg_bridge forwarding shim) is
authoritative for all modules. Importing the package applies os.umask(0o077).

Submodules are loaded lazily: `telecode --help` and the installer only pay for
the CLI module, while a listener or status call imports the transport and
agent layers on demand.
"""
from __future__ import annotations

import importlib

from . import state as _state

_state.configure()

# --- state.py (mutable picker state and limits) ---
from .state import (  # noqa: F401
    INJECT_Q,
    SESSION_PAGE_SIZE,
    MODELS_PAGE_SIZE,
    MODEL_PAGE_STATE,
    MODEL_BACK,
    MODEL_PREVIOUS,
    MODEL_NEXT,
    MODEL_CLOSE,
    NEW_SESSION,
    CREATE_SESSION,
    SESSION_NAME_MAX_LENGTH,
    MODEL_SELECTION,
    SESSION_BUTTONS,
    ACTIVE_PICKER,
    SESSION_PAGE,
    SESSION_SNAPSHOT,
)

# Names that live in heavier submodules. They are imported on first access.
_LAZY_GROUPS = {
    "util": (
        "ts", "log", "load_env", "api", "_updated", "_html_escape",
        "_plain_fallback", "_cursor", "_unread", "_advance",
    ),
    "telegram": (
        "_style_keyboard", "_download_file", "_keyboard", "_configure_commands",
        "_send_keyboard", "_send_inline", "_edit_inline", "send_text",
        "send_file",
    ),
    "agents": (
        "_agent_adapter", "_agent_name", "_agent_identity", "_codex_adapter",
        "_opencode_bin", "_opencode_api", "create_session", "_session_items",
        "list_sessions", "_active_session_id", "_active_session_record",
        "_active_session_matches_agent", "_set_active_session",
        "discover_session", "_session_by_id", "resolve_session", "_try_prompt",
    ),
    "pickers": (
        "_send_picker_notice", "_invalidate_model_message_ref",
        "_hide_picker_keyboard", "session_title", "session_label",
        "_session_buttons", "_send_session_picker", "_begin_new_session",
        "_restore_primary_controls", "_send_reply_picker",
        "_callback_message_ref", "_load_models_message_ref", "_models_from_api",
        "_write_models_cache", "_read_models_cache", "_group_models",
        "_ordered_providers", "_current_model", "_models_menu",
        "_remember_reply_picker_message", "_edit_reply_picker",
        "_set_models_message_ref", "_switch_session_model", "handle_callback",
        "handle_control_message",
    ),
    "routing": (
        "inject_record", "_inject_worker",
    ),
    "listener": (
        "start_opencode_listener", "_remove_pid_file", "cmd_listen",
    ),
}
_LAZY = {name: module for module, names in _LAZY_GROUPS.items() for name in names}


def __getattr__(name):
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY))


# --- cli.py (kept eager: it is tiny and needed for --help) ---
from . import cli as _cli  # noqa: E402
from .cli import (  # noqa: E402,F401
    cmd_read,
    cmd_wait,
    cmd_send,
    cmd_sendfile,
    cmd_status,
    cmd_install,
    main,
    USAGE,
)
