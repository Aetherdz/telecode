"""TeleCode Telegram bridge package.

The package root is the single home for shared mutable bridge state. Every
submodule reads and writes bridge symbols through `import telegram_bridge as tg`
at call time, so patching the root (or the tg_bridge forwarding shim) is
authoritative for all modules. Importing the package applies os.umask(0o077).
"""

from . import state as _state
from . import util
from . import telegram
from . import agents
from . import pickers
from . import routing
from . import listener
from . import cli

_state.configure()

# --- state.py ---
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

# --- util.py ---
from .util import (  # noqa: F401
    ts,
    log,
    load_env,
    api,
    _updated,
    _html_escape,
    _plain_fallback,
    _cursor,
    _unread,
    _advance,
)

# --- telegram.py ---
from .telegram import (  # noqa: F401
    _style_keyboard,
    _download_file,
    _keyboard,
    _configure_commands,
    _send_keyboard,
    _send_inline,
    _edit_inline,
    send_text,
    send_file,
)

# --- agents.py ---
from .agents import (  # noqa: F401
    _agent_adapter,
    _agent_name,
    _agent_identity,
    _codex_adapter,
    _opencode_bin,
    _opencode_api,
    create_session,
    _session_items,
    list_sessions,
    _active_session_id,
    _active_session_record,
    _active_session_matches_agent,
    _set_active_session,
    discover_session,
    _session_by_id,
    resolve_session,
    _try_prompt,
)

# --- pickers.py ---
from .pickers import (  # noqa: F401
    _send_picker_notice,
    _invalidate_model_message_ref,
    _hide_picker_keyboard,
    session_title,
    session_label,
    _session_buttons,
    _send_session_picker,
    _begin_new_session,
    _restore_primary_controls,
    _send_reply_picker,
    _callback_message_ref,
    _load_models_message_ref,
    _models_from_api,
    _write_models_cache,
    _read_models_cache,
    _group_models,
    _ordered_providers,
    _current_model,
    _models_menu,
    _remember_reply_picker_message,
    _edit_reply_picker,
    _set_models_message_ref,
    _switch_session_model,
    handle_callback,
    handle_control_message,
)

# --- routing.py ---
from .routing import (  # noqa: F401
    inject_record,
    _inject_worker,
)

# --- listener.py ---
from .listener import (  # noqa: F401
    start_opencode_listener,
    _remove_pid_file,
    cmd_listen,
)

# --- cli.py ---
from .cli import (  # noqa: F401
    cmd_read,
    cmd_wait,
    cmd_send,
    cmd_sendfile,
    cmd_status,
    cmd_install,
    main,
    USAGE,
)
