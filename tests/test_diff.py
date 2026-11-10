"""The full-set comparison: report shape and exit codes."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIFF = ROOT / "diff.py"


def row(name, types, action="Legal", new_type="LLT_invalid", config="C0"):
    return {"config": config, "name": name, "types": types, "mem": None,
            "imms": [], "action": action, "type_idx": 0, "new_type": new_type}


def write(rows):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for r in rows:
        f.write(json.dumps(r) + "\n")
    f.close()
    return f.name


class Diff(unittest.TestCase):
    def run_diff(self, a, b, *flags):
        pa, pb = write(a), write(b)
        r = subprocess.run(
            [sys.executable, str(DIFF), pa, pb, "--json", *flags],
            capture_output=True, text=True)
        self.assertIn(r.returncode, (0, 1, 2), r.stderr)
        return r.returncode, json.loads(r.stdout)

    def test_agree(self):
        a = [row("G_ADD", ["s32"])]
        rc, r = self.run_diff(a, a)
        self.assertEqual(rc, 0)
        self.assertEqual((r["disagree"], r["missing_ref"], r["missing_ours"]),
                         (0, 0, 0))
        self.assertEqual(r["agree"], 1)

    def test_disagree(self):
        a = [row("G_ADD", ["s64"], "WidenScalar", "s64")]
        b = [row("G_ADD", ["s64"], "Legal", "LLT_invalid")]
        rc, r = self.run_diff(a, b)
        self.assertEqual(rc, 1)
        self.assertEqual(r["disagree"], 1)
        self.assertEqual((r["missing_ref"], r["missing_ours"]), (0, 0))

    def test_missing_on_each_side(self):
        a = [row("G_ADD", ["s32"]), row("G_ADD", ["s64"])]
        b = [row("G_ADD", ["s32"]), row("G_SUB", ["s32"])]
        rc, r = self.run_diff(a, b)
        self.assertEqual(rc, 1)
        self.assertEqual(r["missing_ref"], 1)   # G_SUB only in ours
        self.assertEqual(r["missing_ours"], 1)  # G_ADD s64 only in ref

    def test_symmetric_unanswerable_is_agree(self):
        """agree means "same observable result", not "answered".

        Both sides aborting is an observation: they are in the same state.
        The strict count is carried separately as answered_equal.
        """
        a = [row("G_CTLZ", ["p0:32", "s32"])]
        a[0].update(status="unanswerable", reason="asserted")
        b = [dict(a[0])]
        rc, r = self.run_diff(a, b)
        self.assertEqual(rc, 0)
        self.assertEqual(r["agree"], 1)
        self.assertEqual(r["answered_equal"], 0)
        self.assertEqual(r["unanswerable"], 1)
        self.assertEqual(r["disagree"], 0)
        self.assertEqual(r["agree"] + r["ref_asserted"] + r["disagree"],
                         r["matched"])

    def test_answered_equal_subtracts_the_symmetric_asserts(self):
        answered = row("G_ADD", ["s32"])
        dead = dict(row("G_CTLZ", ["p0:32", "s32"]),
                    status="unanswerable", reason="asserted")
        rc, r = self.run_diff([answered, dead], [answered, dead])
        self.assertEqual(rc, 0)
        self.assertEqual(r["matched"], 2)
        self.assertEqual(r["agree"], 2)
        self.assertEqual(r["answered_equal"], 1)
        self.assertEqual(r["unanswerable"], 1)

    def test_assert_sites_are_compared_when_asked(self):
        a = [row("G_CTPOP", ["f128", "p0:64"])]
        a[0].update(status="unanswerable", reason="asserted",
                    assert_site="LowLevelType.h:429")
        b = [dict(a[0])]
        rc, r = self.run_diff(a, b, "--assert-sites")
        self.assertEqual(rc, 0)
        self.assertEqual(r["disagree"], 0)
        self.assertEqual(r["assert_sites"]["same"], 1)
        self.assertEqual(r["assert_sites"]["mismatch"], 0)
        self.assertEqual(r["assert_sites"]["top"][0][0], "LowLevelType.h:429")

    def test_a_different_site_is_reported_not_counted_as_disagree(self):
        """A site difference is a finding about the *reason*, not the answer.

        Both sides still return "no action", so the diff stays agree; the
        mismatch is surfaced separately and must be explained.
        """
        a = [row("G_CTPOP", ["f128", "p0:64"])]
        a[0].update(status="unanswerable", reason="asserted",
                    assert_site="LowLevelType.h:429")
        b = [dict(a[0], assert_site="LowLevelType.h:151")]
        rc, r = self.run_diff(a, b, "--assert-sites")
        self.assertEqual(rc, 0)
        self.assertEqual(r["disagree"], 0)
        self.assertEqual(r["assert_sites"]["same"], 0)
        self.assertEqual(r["assert_sites"]["mismatch"], 1)

    def test_answerable_and_unanswerable_disagree(self):
        a = [row("G_CTLZ", ["p0:32", "s32"])]
        b = [dict(a[0], status="unanswerable", reason="asserted")]
        rc, r = self.run_diff(a, b)
        self.assertEqual(rc, 1)
        self.assertEqual(r["disagree"], 1)


class Command(unittest.TestCase):
    """The workbench verb's human-readable output and its exit codes."""

    def run_diff(self, a, b):
        pa, pb = write(a), write(b)
        return subprocess.run([sys.executable, str(DIFF), pa, pb],
                              capture_output=True, text=True)

    def test_agree_returns_zero(self):
        rows = [row("G_ADD", ["s32"])]
        r = self.run_diff(rows, rows)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("disagree=0", r.stdout)

    def test_disagree_returns_one(self):
        a = [row("G_ADD", ["s64"], "WidenScalar", "s64")]
        b = [row("G_ADD", ["s64"], "Legal", "LLT_invalid")]
        r = self.run_diff(a, b)
        self.assertEqual(r.returncode, 1)
        self.assertIn("MISMATCH", r.stdout)

    def test_unreadable_line_is_exit_two(self):
        pa, pb = write([row("G_ADD", ["s32"])]), write([row("G_ADD", ["s32"])])
        with open(pa, "a") as f:
            f.write("not json\n")
        r = subprocess.run([sys.executable, str(DIFF), pa, pb],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)



if __name__ == "__main__":
    unittest.main()
