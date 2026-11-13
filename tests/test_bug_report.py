"""`bug-report` must always produce a small, parseable artifact."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run([sys.executable, str(ROOT / "ab.py"), "bug-report",
                           *args],
                          cwd=ROOT, capture_output=True, text=True)


class Report(unittest.TestCase):
    def test_stdout_is_json_with_the_expected_facts(self):
        done = run()
        self.assertEqual(done.returncode, 0, done.stderr)
        doc = json.loads(done.stdout)
        self.assertEqual(doc["schema"], 1)
        self.assertIn("gisel-ab", doc["versions"])
        self.assertIn("gisel", doc["versions"])
        self.assertIsInstance(doc["doctor"]["checks"], list)
        # A missing LLVM tree/build must not turn the report into a failure:
        # the report is the evidence, not the gate.
        self.assertTrue(any(c["name"] == "tree" for c in doc["doctor"]["checks"]))

    def test_out_writes_a_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "nested" / "bug.json"
            done = run("--out", str(out))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("wrote %s" % out, done.stdout)
            self.assertEqual(json.loads(out.read_text())["schema"], 1)


if __name__ == "__main__":
    unittest.main()
