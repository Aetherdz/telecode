#!/usr/bin/env python3
"""
Telegram bridge for the arsenal agent — relay + session wake (no LLM routing).

Owner messages are stored in inbox.jsonl AND injected into the live OpenCode
session so a new Telegram message starts (or steers) an agent turn immediately.
Non-owner messages are never injected.

Session targeting: auto-discovery of the newest root session for this home
directory; OPENCODE_SESSION_ID is a fallback pin (OPENCODE_SESSION_MODE=pin
forces pin-only). Delivery: TG_DELIVERY=steer (default; runs at the next step
boundary, even while the session is busy) or queue (waits for turn end).

Commands:
  listen        daemon: long-polls getUpdates, stores OWNER messages to
                inbox.jsonl and injects them into the live OpenCode session
  read          print unread messages (advances cursor)
  wait SECONDS  block until an unread message arrives or timeout
  send TEXT     send a message to the owner chat (text may also come via stdin)
  sendfile PATH [CAPTION]   send a document to the owner chat
  status        bot identity, unread count, listener state, inject target

Security:
  - Only messages from TG_CHAT_ID are accepted; everything else is ignored.
  - Config lives in telegram.env (chmod 600).
  - Injection can be disabled with OPENCODE_INJECT=0 in telegram.env.

This file is the installed entry point; the implementation lives in the
telegram_bridge package next to it. Module attributes are forwarded to the
package so patching `tg_bridge.X` still governs every submodule call.
"""
import subprocess
import sys
import types

import telegram_bridge as _pkg

# Snapshot of the package's bridge symbols. Patch/restore of these must always
# land on the package root: a live hasattr() check would misroute the restore
# that follows mock's teardown delattr (the package no longer has the name at
# that instant), leaving submodule tg.X lookups broken.
_FORWARD_NAMES = frozenset(n for n in vars(_pkg) if not n.startswith("__"))
# Names owned by this shim module rather than the package root.
_SHIM_LOCAL = frozenset({
    "_pkg", "_FORWARD_NAMES", "_SHIM_LOCAL", "_Forwarder", "atexit", "json",
    "os", "pathlib", "queue", "re", "secrets", "signal", "stat", "subprocess",
    "sys", "threading", "time", "traceback", "types", "urllib",
})


class _Forwarder(types.ModuleType):
    """Forward module attribute reads/writes to the telegram_bridge package."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        try:
            return getattr(_pkg, name)
        except AttributeError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        # Forward every public bridge symbol, including lazily loaded ones. The
        # package exports are not all in vars() at import time any more.
        if name.startswith("__") or name in _SHIM_LOCAL:
            super().__setattr__(name, value)
        else:
            setattr(_pkg, name, value)

    def __delattr__(self, name):
        if name.startswith("__") or name in _SHIM_LOCAL:
            super().__delattr__(name)
        else:
            delattr(_pkg, name)

    def __dir__(self):
        return sorted(set(super().__dir__()) | set(dir(_pkg)))


if __name__ != "__main__":
    sys.modules[__name__].__class__ = _Forwarder

if __name__ == "__main__":
    raise SystemExit(_pkg.main())
