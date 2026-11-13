"""``python3 -m gisel_ab`` is the installed entry point (needs ``src`` on PYTHONPATH)."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
