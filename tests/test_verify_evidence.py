"""verify-evidence.sh must fail when a MIR report stops saying what it said."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "verify-evidence.sh"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_entry(tmp, totals=None, restored=True):
    report = {
        "schema": 1,
        "layer": "upstream",
        "llc_sha256": "ef74d1ab",
        "totals": {"runs": 624, "same": 611, "both_abort": 13, "diff": 0},
        "targets": {"x86": {"runs": 140, "same": 140, "diff": 0}},
    }
    provenance = {
        "targets": {"x86": {"baseline_lib_restored_exactly": restored}},
    }
    (tmp / "mir-report.json").write_text(json.dumps(report))
    (tmp / "provenance.json").write_text(json.dumps(provenance))
    return {
        "id": "MIR-L1/upstream",
        "kind": "mir",
        "direction": "MIR",
        "target": "x86",
        "command": "make-entry",
        "dir": str(tmp),
        "artifacts": {"mir-report.json": sha(tmp / "mir-report.json"),
                      "provenance.json": sha(tmp / "provenance.json")},
        "expect": {
            "mir": totals or {"runs": 624, "same": 611, "both_abort": 13,
                              "diff": 0},
            "mir_targets": {"x86": {"same": 140, "diff": 0}},
            "llc_sha256": "ef74d1ab",
        },
    }


class MirEvidence(unittest.TestCase):
    def run_verify(self, entry):
        tmp = Path(tempfile.mkdtemp())
        manifest = tmp / "EVIDENCE.json"
        manifest.write_text(json.dumps({"schema": 1, "entries": [entry]}))
        env = dict(os.environ, VERIFY_MANIFEST=str(manifest))
        return subprocess.run([str(SCRIPT), "MIR"], capture_output=True,
                              text=True, env=env), Path(entry["dir"])

    def test_matching_report_passes(self):
        tmp = Path(tempfile.mkdtemp())
        proc, _ = self.run_verify(make_entry(tmp))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("1/1 entries pass", proc.stdout)

    def test_totals_drift_fails_even_when_the_file_hashes(self):
        tmp = Path(tempfile.mkdtemp())
        entry = make_entry(tmp, totals={"runs": 624, "same": 999,
                                        "both_abort": 13, "diff": 0})
        proc, _ = self.run_verify(entry)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("totals same=611, expected 999", proc.stdout)

    def test_a_failed_restore_fails(self):
        tmp = Path(tempfile.mkdtemp())
        proc, _ = self.run_verify(make_entry(tmp, restored=False))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("baseline library not restored", proc.stdout)


class SummaryEvidence(unittest.TestCase):
    """A per-config domain run aggregates into summary.json, not one diff."""

    def run_verify(self, entry):
        tmp = Path(tempfile.mkdtemp())
        manifest = tmp / "EVIDENCE.json"
        manifest.write_text(json.dumps({"schema": 1, "entries": [entry]}))
        env = dict(os.environ, VERIFY_MANIFEST=str(manifest))
        return subprocess.run([str(SCRIPT), "D"], capture_output=True,
                              text=True, env=env)

    def make(self, tmp, agree=112, expected_agree=None):
        summary = {"target": "m68k", "configs": 1, "queries": 112,
                   "agree": agree, "disagree": 0,
                   "unanswerable": 0, "ref_asserted": 0,
                   "errors": 0, "per_config": []}
        (tmp / "summary.json").write_text(json.dumps(summary))
        return {
            "id": "D/m68k", "kind": "summary", "direction": "D",
            "target": "m68k", "command": "make-summary", "dir": str(tmp),
            "artifacts": {"summary.json": sha(tmp / "summary.json")},
            "expect": {"summary": {"configs": 1, "queries": 112,
                                   "agree": expected_agree if expected_agree
                                   is not None else agree,
                                   "disagree": 0, "unanswerable": 0,
                                   "ref_asserted": 0, "errors": 0}},
        }

    def test_summary_entry_passes_without_a_diff(self):
        proc = self.run_verify(self.make(Path(tempfile.mkdtemp())))
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_summary_drift_fails(self):
        proc = self.run_verify(self.make(Path(tempfile.mkdtemp()), agree=111,
                                         expected_agree=112))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("summary agree=111, expected 112", proc.stdout)


def make_lit_entry(tmp, tests=None, swapped_same=False):
    tests = tests or {"LLVM :: a.ll": ("PASS", True),
                      "LLVM :: b.ll": ("FAIL", True)}
    counts = {"tests": len(tests), "passed": 1, "xfail": 1, "failed": 0,
              "xpass": 0, "unsupported": 0, "aborted": 0}
    log = {"discovered": 3, "skipped": 1, "unsupported": 0, "passed": 1,
           "xfail": 1}
    summary = {"baseline": counts, "combined": counts,
               "log.baseline": log, "log.combined": log,
               "tests_compared": len(tests), "identical": True,
               "only_in_baseline": [], "only_in_combined": [], "changed": []}
    libs = {"baseline": {"x86": "aa"}, "swapped": {"x86": "aa" if swapped_same
                                                   else "bb"},
            "restored": {"x86": "aa"},
            "restored_exactly": {"x86": True}}
    provenance = {"tree_clean_after": True, "libs": libs}
    for side in ("baseline", "combined"):
        (tmp / ("l3-%s.tests.jsonl" % side)).write_text("".join(
            json.dumps({"test": name, "status": status, "expected": expected},
                       sort_keys=True) + "\n"
            for name, (status, expected) in sorted(tests.items())))
    (tmp / "l3-summary.json").write_text(json.dumps(summary))
    (tmp / "l3-provenance.json").write_text(json.dumps(provenance))
    return {
        "id": "MIR-L3/check-llvm", "kind": "lit", "direction": "MIR",
        "target": "x86+aarch64+riscv", "command": "make-lit", "dir": str(tmp),
        "artifacts": {name: sha(tmp / name) for name in (
            "l3-summary.json", "l3-provenance.json",
            "l3-baseline.tests.jsonl", "l3-combined.tests.jsonl")},
        "expect": {"lit": {"baseline": counts, "combined": counts,
                           "log.baseline": log, "log.combined": log,
                           "tests_compared": len(tests), "identical": True}},
    }


class LitEvidence(unittest.TestCase):
    """L3 is re-derived from the per-test records, not from the summary."""

    def run_verify(self, entry):
        tmp = Path(tempfile.mkdtemp())
        manifest = tmp / "EVIDENCE.json"
        manifest.write_text(json.dumps({"schema": 1, "entries": [entry]}))
        env = dict(os.environ, VERIFY_MANIFEST=str(manifest))
        return subprocess.run([str(SCRIPT), "MIR"], capture_output=True,
                              text=True, env=env)

    def test_matching_rounds_pass(self):
        proc = self.run_verify(make_lit_entry(Path(tempfile.mkdtemp())))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("1/1 entries pass", proc.stdout)

    def test_a_changed_test_fails_even_when_the_summary_claims_identity(self):
        tmp = Path(tempfile.mkdtemp())
        entry = make_lit_entry(tmp)
        # Flip one test in the frozen combined round; the summary still says
        # identical because it was written before the edit, and its sha is
        # re-recorded so only the recomputation can catch this.
        path = tmp / "l3-combined.tests.jsonl"
        path.write_text(path.read_text().replace(
            '"status": "FAIL"', '"status": "PASS"'))
        entry["artifacts"]["l3-combined.tests.jsonl"] = sha(path)
        proc = self.run_verify(entry)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("changed result", proc.stdout)

    def test_a_noop_swap_fails(self):
        proc = self.run_verify(make_lit_entry(Path(tempfile.mkdtemp()),
                                              swapped_same=True))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("library was identical after the swap", proc.stdout)


if __name__ == "__main__":
    unittest.main()
