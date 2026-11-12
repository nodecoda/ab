"""l3.py compare: equal totals are not the same as an equal test set."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "l3.py"

LOG = """\
-- Testing: 3 tests, 3 workers --
Testing Time: 0.10s

Total Discovered Tests: 3
  Skipped          :     0 (0.00%)
  Unsupported      :     0 (0.00%)
  Passed           : {passed} (0.00%)
  Expectedly Failed: {xfail} (0.00%)
"""


def write_round(out, side, tests, passed=1, xfail=1):
    rows = [{"testId": name, "status": status, "expected": expected}
            for name, (status, expected) in tests.items()]
    (out / ("%s.resultdb.json" % side)).write_text(
        json.dumps({"tests": rows}))
    (out / ("%s.lit.log" % side)).write_text(LOG.format(passed=passed,
                                                         xfail=xfail))


class Compare(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def compare(self, baseline, combined, **kwargs):
        write_round(self.dir, "baseline", baseline, **kwargs)
        write_round(self.dir, "combined", combined, **kwargs)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "compare", str(self.dir),
             "--json", str(self.dir / "l3-summary.json")],
            capture_output=True, text=True)
        summary = json.loads((self.dir / "l3-summary.json").read_text())
        return proc, summary

    def test_identical_rounds_pass_and_leave_per_test_records(self):
        tests = {"LLVM :: a.ll": ("PASS", True), "LLVM :: b.ll": ("FAIL", True)}
        proc, summary = self.compare(tests, dict(tests))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertTrue(summary["identical"])
        self.assertEqual(summary["tests_compared"], 2)
        self.assertEqual(summary["log.baseline"]["discovered"], 3)
        self.assertEqual(len((self.dir / "l3-baseline.tests.jsonl")
                             .read_text().splitlines()), 2)

    def test_a_pass_xfail_swap_with_equal_totals_fails(self):
        # The reason the comparison reads ResultDB: xunit prints XFAIL as a
        # passing testcase, and the two rounds below have identical totals.
        baseline = {"LLVM :: a.ll": ("FAIL", True),
                    "LLVM :: b.ll": ("PASS", True)}
        combined = {"LLVM :: a.ll": ("PASS", True),
                    "LLVM :: b.ll": ("FAIL", True)}
        proc, summary = self.compare(baseline, combined)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(summary["identical"])
        self.assertEqual(summary["baseline"], summary["combined"])
        self.assertEqual([row["test"] for row in summary["changed"]],
                         ["LLVM :: a.ll", "LLVM :: b.ll"])

    def test_a_test_that_exists_on_one_side_fails(self):
        proc, summary = self.compare({"LLVM :: a.ll": ("PASS", True)},
                                     {"LLVM :: b.ll": ("PASS", True)})
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(summary["only_in_baseline"], ["LLVM :: a.ll"])
        self.assertEqual(summary["only_in_combined"], ["LLVM :: b.ll"])


if __name__ == "__main__":
    unittest.main()
