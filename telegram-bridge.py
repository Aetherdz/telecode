#!/usr/bin/env python3
"""TeleCode CLI entry point."""
import sys
import os
import pathlib
os.environ.setdefault("TELEGRAM_BRIDGE_HOME", str(pathlib.Path.home() / ".config" / "telegram-bridge"))
import tg_bridge

if __name__ == "__main__":
    sys.exit(tg_bridge.main())
