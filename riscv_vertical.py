#!/usr/bin/env python3
"""Backwards-compatible entry point for the RISC-V slice.

The implementation moved to `vertical.py`, which takes `--target`.  This file
stays so old commands, docs and tests keep working:

    python3 riscv_vertical.py …      ==  python3 vertical.py --target riscv …
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vertical  # noqa: E402

parse_l3 = vertical.parse_l3
sha256 = vertical.sha256
TARGETS = vertical.TARGETS

if __name__ == "__main__":
    sys.exit(vertical.main(sys.argv[1:], default_target="riscv"))
