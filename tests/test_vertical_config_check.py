"""vertical.py must actually exercise the config->llc mapping.

`mir-config-check.py` was an orphan: documented, never called.  A fake llc is
enough to prove the slice runs both the check and its `--mutate` control,
without an LLVM build.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERTICAL = ROOT / "vertical.py"


def load():
    spec = importlib.util.spec_from_file_location("vertical", VERTICAL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeLlc(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.build = self.root / "build"
        (self.build / "bin").mkdir(parents=True)
        llc = self.build / "bin" / "llc"
        llc.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in\n"
            "  *-mattr=help*)\n"
            "    echo '  sse   - SSE'\n"
            "    echo '  sse2  - SSE2'\n"
            "    echo '  x87   - X87'\n"
            "    ;;\n"
            "esac\n"
            "exit 0\n")
        llc.chmod(0o755)
        self.features = self.root / "features.json"
        self.features.write_text(json.dumps({"C0": {}}))
        self.out = self.root / "out"
        self.out.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_check_and_its_negative_control_both_run(self):
        module = load()
        module.config_check("x86", {"features": str(self.features)},
                            self.build, self.out)
        check = json.loads((self.out / "mir-config-check.json").read_text())
        self.assertTrue(check["ok"], check["problems"])
        control = json.loads(
            (self.out / "mir-config-check-mutate.json").read_text())
        self.assertFalse(control["ok"], "the mutated config was still accepted")
        self.assertTrue(any("not-a-real-subtarget-feature" in problem
                            for problem in control["problems"]))

    def test_a_missing_llc_is_a_stop(self):
        module = load()
        (self.build / "bin" / "llc").unlink()
        with self.assertRaises(SystemExit):
            module.config_check("x86", {"features": str(self.features)},
                                self.build, self.out)


if __name__ == "__main__":
    unittest.main()
