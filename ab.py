#!/usr/bin/env python3
"""Checkout entry point: ``python3 ab.py <verb>``.

An editable install exposes ``gisel-ab``; this file exists so a fresh clone
works without one.  It is the only ``.py`` allowed at the repository root.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from gisel_ab.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
