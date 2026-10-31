"""Small, dependency-free terminal styling helpers for TeleCode.

All colour decisions live here so the installer, the setup selector, and the
CLI render consistently. Nothing is written to stdout on import.
"""
from __future__ import annotations

import os
import re
import sys

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

# Colors use the same accent as the installer wordmark.
ACCENT = "1;38;2;48;179;239"
BOLD = "1"
DIM = "2"
GREEN = "32"
YELLOW = "33"
RED = "31"


def _stream(stream=None):
    return sys.stdout if stream is None else stream


def supports_color(stream=None) -> bool:
    """True only for a real TTY with NO_COLOR/TERM/dumb respected."""
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return bool(getattr(_stream(stream), "isatty", lambda: False)())


def supports_unicode(stream=None) -> bool:
    """Best-effort UTF-8 check for glyphs such as the check mark."""
    if not supports_color(stream):
        return False
    encoding = getattr(_stream(stream), "encoding", None) or ""
    return "utf" in encoding.lower()


def paint(text, *codes, stream=None) -> str:
    if not supports_color(stream):
        return text
    return "\033[" + ";".join(codes) + "m" + text + "\033[0m"


def bold(text, stream=None) -> str:
    return paint(text, BOLD, stream=stream)


def dim(text, stream=None) -> str:
    return paint(text, DIM, stream=stream)


def accent(text, stream=None) -> str:
    return paint(text, ACCENT, stream=stream)


def green(text, stream=None) -> str:
    return paint(text, GREEN, stream=stream)


def yellow(text, stream=None) -> str:
    return paint(text, YELLOW, stream=stream)


def red(text, stream=None) -> str:
    return paint(text, RED, stream=stream)


def icon(ok: bool, stream=None) -> str:
    if supports_unicode(stream):
        return "✓" if ok else "✗"
    return "ok" if ok else "error"


def ok_line(text, stream=None) -> str:
    return f"{green(icon(True, stream), stream)} {text}"


def warn_line(text, stream=None) -> str:
    return f"{yellow('!', stream)} {text}"


def error_line(text, stream=None) -> str:
    return f"{red(icon(False, stream), stream)} {text}"


def mask_token(token: str, visible: int = 4, unicode: bool | None = None) -> str:
    """Return ``12345••••••abcd`` without ever exposing the secret part."""
    account, _, secret = str(token).partition(":")
    if not secret:
        return mask_value(token, visible)
    hidden = "•" * 6 if (unicode is True or (unicode is None and supports_unicode())) else "*" * 6
    return f"{account}{hidden}{secret[-visible:]}"


def mask_value(value: str, visible: int = 4) -> str:
    """Mask an identifier such as a chat ID while keeping its last digits."""
    text = str(value)
    if len(text) <= visible:
        return "*" * len(text)
    return "*" * (len(text) - visible) + text[-visible:]


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def visible_width(text: str) -> int:
    return len(strip_ansi(text))


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - visible_width(text))
