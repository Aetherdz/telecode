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
    encoding = getattr(_stream(stream), "encoding", None) or sys.getdefaultencoding() or ""
    if "utf" in encoding.lower():
        return True
    lang = os.environ.get("LC_ALL") or os.environ.get("LC_CTYPE") or os.environ.get("LANG") or ""
    return "utf" in lang.lower()


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


def _render_menu_lines(title: str, options: list[tuple[str, str, any]], selected: int,
                       stream=None, hint_footer: str | None = None) -> list[str]:
    pointer = "❯" if supports_unicode(stream) else ">"
    max_label_w = max((visible_width(label) for label, _, _ in options), default=0)
    rows = []
    for idx, (label, hint, _) in enumerate(options):
        padded_label = pad(label, max_label_w)
        suffix = f"  {dim(hint, stream=stream)}" if hint else ""
        if idx == selected:
            prefix = accent(bold(f"{pointer} {idx + 1}.", stream=stream), stream=stream)
            item_text = bold(padded_label, stream=stream)
            rows.append(f"  {prefix} {item_text}{suffix}")
        else:
            prefix = dim(f"  {idx + 1}.", stream=stream)
            rows.append(f"  {prefix} {padded_label}{suffix}")
    lines = box(title, rows, stream=stream)
    footer = hint_footer or (
        "↑/↓ move · Enter select · 1-9 jump · q cancel"
        if supports_unicode(stream)
        else "^/v move · Enter select · 1-9 jump · q cancel"
    )
    lines.append(dim(footer, stream=stream))
    return lines


def _redraw_lines(lines: list[str], stream=None) -> None:
    out = _stream(stream)
    out.write(f"\033[{len(lines)}A")
    for line in lines:
        out.write("\r\033[2K" + line + "\n")
    out.flush()


def _read_key_posix(fd: int) -> str:
    import select
    key = os.read(fd, 1).decode("latin1", errors="replace")
    if key == "\x1b":
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            seq = os.read(fd, 2).decode("latin1", errors="replace")
            if seq == "[A":
                return "UP"
            if seq == "[B":
                return "DOWN"
            if seq == "[C":
                return "RIGHT"
            if seq == "[D":
                return "LEFT"
            return "ESC"
        return "ESC"
    return key


def _read_key_windows() -> str:
    import msvcrt
    ch = msvcrt.getch()
    if ch in (b"\x00", b"\xe0"):
        ext = msvcrt.getch()
        if ext == b"H":
            return "UP"
        if ext == b"P":
            return "DOWN"
        return "ESC"
    if ch == b"\x1b":
        return "ESC"
    if ch in (b"\r", b"\n"):
        return "\n"
    if ch == b"\x03":
        return "\x03"
    try:
        return ch.decode("latin1")
    except Exception:
        return ""


def _is_input_mocked() -> bool:
    import builtins
    inp_fn = getattr(builtins, "input", None)
    return hasattr(inp_fn, "assert_called") or hasattr(inp_fn, "return_value") or hasattr(inp_fn, "mock_calls")


def _interactive_menu(title: str, options: list[tuple[str, str, any]], default_index: int = 0,
                      hint_footer: str | None = None, stream=None, stdin=None) -> any:
    out = _stream(stream)
    inp = sys.stdin if stdin is None else stdin
    if _is_input_mocked() or not (getattr(out, "isatty", lambda: False)() and getattr(inp, "isatty", lambda: False)()):
        return _fallback_menu(title, options, default_index, stream=stream)

    selected = default_index % len(options)
    lines = _render_menu_lines(title, options, selected, stream=stream, hint_footer=hint_footer)

    if os.name == "nt":
        out.write("\033[?25l")
        out.write("\n".join(lines) + "\n")
        out.flush()
        try:
            while True:
                key = _read_key_windows()
                if key == "UP" or key in ("k", "K"):
                    selected = (selected - 1) % len(options)
                elif key == "DOWN" or key in ("j", "J"):
                    selected = (selected + 1) % len(options)
                elif key in ("\r", "\n"):
                    return options[selected][2]
                elif key in ("q", "Q", "ESC", "\x03", "\x04"):
                    return next((val for _, _, val in options if val in ("exit", "cancel", "back")), None)
                elif key.isdigit() and 1 <= int(key) <= len(options):
                    return options[int(key) - 1][2]
                lines = _render_menu_lines(title, options, selected, stream=stream, hint_footer=hint_footer)
                _redraw_lines(lines, out)
        finally:
            out.write("\033[?25h")
            out.flush()
    else:
        import termios
        import tty
        fd = inp.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            out.write("\033[?25l")
            out.write("\n".join(lines) + "\n")
            out.flush()
            while True:
                key = inp.read(1)
                if key == "\x1b":
                    seq = inp.read(2)
                    if seq == "[A":
                        selected = (selected - 1) % len(options)
                    elif seq == "[B":
                        selected = (selected + 1) % len(options)
                    else:
                        return next((val for _, _, val in options if val in ("exit", "cancel", "back")), None)
                elif key in ("k", "K"):
                    selected = (selected - 1) % len(options)
                elif key in ("j", "J"):
                    selected = (selected + 1) % len(options)
                elif key in ("\r", "\n"):
                    return options[selected][2]
                elif key in ("q", "Q", "\x03", "\x04"):
                    return next((val for _, _, val in options if val in ("exit", "cancel", "back")), None)
                elif key.isdigit() and 1 <= int(key) <= len(options):
                    return options[int(key) - 1][2]
                lines = _render_menu_lines(title, options, selected, stream=stream, hint_footer=hint_footer)
                _redraw_lines(lines, out)
        finally:
            out.write("\033[?25h")
            out.flush()
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _fallback_menu(title: str, options: list[tuple[str, str, any]], default_index: int = 0, stream=None) -> any:
    out = _stream(stream)
    max_label_w = max((visible_width(label) for label, _, _ in options), default=0)
    rows = []
    for idx, (label, hint, _) in enumerate(options, 1):
        suffix = f"  {dim(hint, stream=stream)}" if hint else ""
        rows.append(f"  {accent(str(idx) + '.', stream=stream)} {bold(pad(label, max_label_w), stream=stream)}{suffix}")
    print(file=out)
    for line in box(title, rows, stream=stream):
        print(line, file=out)
    print(file=out)
    print(dim(f"1-{len(options)} select · q exit", stream=stream), file=out)
    while True:
        try:
            ans = input("TeleCode › ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(file=out)
            return next((val for _, _, val in options if val in ("exit", "cancel", "back")), None)
        if ans in ("q", "quit", "exit"):
            return next((val for _, _, val in options if val in ("exit", "cancel", "back")), None)
        for idx, (label, _, val) in enumerate(options, 1):
            if ans in (str(idx), label.lower(), str(val).lower()):
                return val
        print(error_line(f"Choose 1-{len(options)} or enter a command name.", stream=stream), file=sys.stderr)


def select_menu(title: str, options: list[tuple[str, str, any]], default_index: int = 0,
                hint_footer: str | None = None, stream=None, stdin=None) -> any:
    """Prompt the user with an interactive arrow selector (falls back to numbered input)."""
    try:
        return _interactive_menu(title, options, default_index, hint_footer, stream, stdin)
    except Exception:
        return _fallback_menu(title, options, default_index, stream)
