"""Small, dependency-free terminal styling and TUI helpers for TeleCode.

All colour and terminal layout decisions live here so the installer, the
setup selector, and the CLI render consistently. Nothing is written to
stdout on import.
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

# Colors use the same accent as the installer wordmark (RGB 48, 179, 239).
ACCENT = "1;38;2;48;179;239"
BOLD = "1"
DIM = "2"
GREEN = "32"
YELLOW = "33"
RED = "31"
CYAN = "36"
MAGENTA = "35"
BLUE = "34"
GRAY = "90"
WHITE = "37"


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
    """Best-effort UTF-8 check for glyphs such as box corners and check marks."""
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


def cyan(text, stream=None) -> str:
    return paint(text, CYAN, stream=stream)


def magenta(text, stream=None) -> str:
    return paint(text, MAGENTA, stream=stream)


def blue(text, stream=None) -> str:
    return paint(text, BLUE, stream=stream)


def gray(text, stream=None) -> str:
    return paint(text, GRAY, stream=stream)


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


def status_dot(alive: bool | None, stream=None) -> str:
    """Return a colored status dot or icon for service state."""
    if not supports_unicode(stream):
        if alive is True:
            return green("[up]", stream)
        if alive is False:
            return red("[down]", stream)
        return yellow("[warn]", stream)
    if alive is True:
        return green("●", stream)
    if alive is False:
        return red("○", stream)
    return yellow("▲", stream)


def badge(text: str, tone: str = "accent", stream=None) -> str:
    """Return a styled status badge like [ACTIVE]."""
    painter = globals().get(tone, accent)
    return painter(f"[{text}]", stream=stream)


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
    """Accurately compute display width handling ANSI escapes, wide & combining chars."""
    plain = strip_ansi(str(text))
    width = 0
    for index, char in enumerate(plain):
        if unicodedata.combining(char):
            continue
        if char == "\u200d" or (index and plain[index - 1] == "\u200d"):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - visible_width(text))


def box(title: str | None, rows: list[str], width: int | None = None, stream=None) -> list[str]:
    """Render rows inside a styled terminal box (rounded corners with ASCII fallback)."""
    uni = supports_unicode(stream)
    tl = "╭" if uni else "+"
    tr = "╮" if uni else "+"
    bl = "╰" if uni else "+"
    br = "╯" if uni else "+"
    horiz = "─" if uni else "-"
    vert = "│" if uni else "|"

    max_row_len = max((visible_width(r) for r in rows), default=0)
    title_len = visible_width(title) if title else 0
    calculated_width = max(max_row_len + 4, title_len + 6, 44)
    if width is not None:
        calculated_width = max(calculated_width, width)
    inner = calculated_width - 2

    lines = []
    if title:
        heading = f" {title} "
        head_disp = f" {bold(accent(title, stream), stream)} "
        pad_right = max(0, inner - 1 - len(heading))
        top_line = dim(tl + horiz, stream) + head_disp + dim(horiz * pad_right + tr, stream)
    else:
        top_line = dim(tl + horiz * inner + tr, stream)
    lines.append(top_line)

    for row in rows:
        row_padded = pad(row, inner - 2)
        lines.append(f"{dim(vert, stream)} {row_padded} {dim(vert, stream)}")

    bottom_line = dim(bl + horiz * inner + br, stream)
    lines.append(bottom_line)
    return lines


def key_value_card(title: str, items: list[tuple[str, str]], width: int | None = None, stream=None) -> list[str]:
    """Render aligned key-value pairs inside a styled box/card."""
    if not items:
        return box(title, [dim("(empty)", stream)], width=width, stream=stream)
    label_w = max(visible_width(k) for k, _ in items)
    rows = []
    for k, v in items:
        rows.append(f"{dim(pad(k, label_w), stream)}  {v}")
    return box(title, rows, width=width, stream=stream)


def format_message(record: dict, stream=None) -> list[str]:
    """Format an incoming Telegram update as a clean, readable card."""
    iso = record.get("iso", "")
    text = record.get("text", "")
    file_path = record.get("file")
    update_id = record.get("update_id", "")

    header = f"{accent(f'[{iso}]', stream)} {dim(f'#{update_id}', stream)}" if iso else dim(f"#{update_id}", stream)
    lines = [f"{header} {text}"]
    if file_path:
        lines.append(f"    {dim('Attachment:', stream)} {cyan(file_path, stream)}")
    return lines
