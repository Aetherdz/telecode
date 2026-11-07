"""Direct entry point for running `python3 -m telegram_bridge`."""
import sys
from telegram_bridge.cli import main

if __name__ == "__main__":
    sys.exit(main())
