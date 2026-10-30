"""Shared paths, mutable picker state, and bootstrap for the bridge package."""
import os
import pathlib
import queue


def configure(home=None):
    """Rebind the path globals on the package root (the single home)."""
    import telegram_bridge as tg
    base = pathlib.Path(home if home is not None else os.environ.get(
        "TELEGRAM_BRIDGE_HOME", str(pathlib.Path(os.environ.get("XDG_CONFIG_HOME", pathlib.Path.home() / ".config")) / "telegram-bridge")
    )).expanduser().resolve()
    tg.BASE = base
    tg.ENV = base / "telegram.env"
    tg.INBOX = base / "inbox.jsonl"
    tg.OFFSET = base / "offset.txt"
    tg.CURSOR = base / "cursor.txt"
    tg.PID = base / "listener.pid"
    tg.FILES = base / "files"
    tg.STATE = base / "wake-session.txt"
    tg.ACTIVE_SESSION = base / "active-session.json"
    tg.MODELS_CACHE = base / "models-cache.json"


configure()
os.umask(0o077)

INJECT_Q: "queue.Queue[dict]" = queue.Queue()
SESSION_PAGE_SIZE = 20
MODELS_PAGE_SIZE = 20
MODEL_PAGE_STATE = {"provider_index": None, "page": 0}
MODEL_BACK = "Back to providers"
MODEL_PREVIOUS = "Previous"
MODEL_NEXT = "Next"
MODEL_CLOSE = "Cancel"
NEW_SESSION = "New session"
CREATE_SESSION = "Create session"
SESSION_NAME_MAX_LENGTH = 80
MODEL_SELECTION = {"provider": None, "page": 0, "labels": {}}
SESSION_BUTTONS = {}
ACTIVE_PICKER = None
SESSION_PAGE = 0
SESSION_SNAPSHOT = []
