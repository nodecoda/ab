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


class RefAssertSites(unittest.TestCase):
    """ref_asserted is classified by where the reference died, not just how
    many times: a total can stay flat while one assert class replaces another.
    """

    def run_diff(self, a, b, *flags):
        pa, pb = write(a), write(b)
        r = subprocess.run(
            [sys.executable, str(DIFF), pa, pb, "--json", *flags],
            capture_output=True, text=True)
        self.assertIn(r.returncode, (0, 1, 2), r.stderr)
        return r.returncode, json.loads(r.stdout)

    def rows(self):
        dead = {"config": "C0", "name": "G_ICMP", "types": ["s1", "p0"],
                "mem": None, "imms": [], "status": "unanswerable",
                "reason": "asserted"}
        a = [dict(dead, assert_site="LegalizerInfo.cpp:200", types=["s1", "p0"]),
             dict(dead, assert_site="LegalizerInfo.cpp:200", types=["s2", "p0"]),
             dict(dead, name="G_FPTOSI", assert_site="LowLevelType.h:429",
                  types=["s32"])]
        b = [row("G_ICMP", ["s1", "p0"]), row("G_ICMP", ["s2", "p0"]),
             row("G_FPTOSI", ["s32"])]
        return a, b

    def test_sites_and_opcodes_are_counted(self):
        a, b = self.rows()
        rc, r = self.run_diff(a, b, "--allow-ref-asserts", "3")
        self.assertEqual(rc, 0)
        self.assertEqual(r["ref_asserted"], 3)
        self.assertEqual(r["ref_asserted_by_site"],
                         {"LegalizerInfo.cpp:200": 2, "LowLevelType.h:429": 1})
        self.assertEqual(r["ref_asserted_by_opcode"],
                         {"G_ICMP": 2, "G_FPTOSI": 1})

    def test_a_matching_site_pin_passes(self):
        a, b = self.rows()
        rc, _ = self.run_diff(
            a, b, "--allow-ref-asserts",
            "LegalizerInfo.cpp:200=2,LowLevelType.h:429=1")
        self.assertEqual(rc, 0)

    def test_a_new_site_fails_even_when_the_total_is_unchanged(self):
        a, b = self.rows()
        rc, r = self.run_diff(
            a, b, "--allow-ref-asserts",
            "LegalizerInfo.cpp:200=3,LowLevelType.h:429=0")
        self.assertEqual(rc, 1)
        self.assertEqual(r["ref_asserted_by_site"]["LowLevelType.h:429"], 1)

    def test_a_count_that_moved_fails(self):
        a, b = self.rows()
        rc, _ = self.run_diff(
            a, b, "--allow-ref-asserts",
            "LegalizerInfo.cpp:200=1,LowLevelType.h:429=2")
        self.assertEqual(rc, 1)

    def test_a_json_pin_file_works(self):
        a, b = self.rows()
        pin = Path(write([]))
        pin = pin.with_suffix(".json")
        pin.write_text(json.dumps({"LegalizerInfo.cpp:200": 2,
                                   "LowLevelType.h:429": 1}))
        pa, pb = write(a), write(b)
        r = subprocess.run(
            [sys.executable, str(DIFF), pa, pb, "--json",
             "--allow-ref-asserts", "@" + str(pin)],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


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
