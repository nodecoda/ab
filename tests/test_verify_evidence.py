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


if __name__ == "__main__":
    unittest.main()
