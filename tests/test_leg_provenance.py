"""The U leg must build from the same tree/build the contract names."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GISEL = Path(os.environ.get("GISEL_SRC") or ROOT.parent / "gisel")

BUILDER = """#!/usr/bin/env bash
set -euo pipefail
printf '%s|%s\\n' "$1" "$2" > "$FAKE_RECORD"
: > "${4}.official"
: > "${4}.ours"
"""

RUN_QUERIES = """#!/usr/bin/env python3
import pathlib, sys
pathlib.Path(sys.argv[3]).write_text("")
"""

DIFF = """#!/usr/bin/env python3
print('{"agree": 0, "disagree": 0, "unanswerable": 0}')
"""

ATTRIBUTION = """#!/usr/bin/env python3
print('{}')
"""


class ULegProvenance(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ab-u-leg-"))
        for name in ("run-u-end-to-end.sh", "env.sh", "targets.py"):
            (self.dir / name).symlink_to(ROOT / name)
        for name, body in (("build-x86-ctor-runner.sh", BUILDER),
                           ("run-queries.py", RUN_QUERIES),
                           ("diff.py", DIFF),
                           ("u-attribution.py", ATTRIBUTION)):
            path = self.dir / name
            path.write_text(body)
            path.chmod(0o755)
        self.queries = self.dir / "queries.jsonl"
        self.queries.write_text('{"config": "C0"}\n')
        self.inc = self.dir / "X86LegalizerInfo.inc"
        self.inc.write_text("// generated\n")
        self.record = self.dir / "record.txt"

    def test_explicit_tree_and_build_reach_the_builder(self):
        env = dict(os.environ, GISEL_SRC=str(GISEL),
                   U_INC=str(self.inc), FAKE_RECORD=str(self.record))
        proc = subprocess.run(
            ["bash", str(self.dir / "run-u-end-to-end.sh"), "x86",
             str(self.queries), str(self.dir / "out"),
             "--tree", "/tmp/tree-A", "--build", "/tmp/build-B"],
            cwd=self.dir, env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.record.read_text().strip(),
                         "/tmp/tree-A|/tmp/build-B")


if __name__ == "__main__":
    unittest.main()
