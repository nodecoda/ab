"""One e2e implementation: the per-target scripts are shims over run-e2e.sh."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import targets  # noqa: E402

NAMES = [name for name in targets.names() if name != "x86-ctor"]


def plan(target):
    proc = subprocess.run(
        ["bash", str(ROOT / "run-e2e.sh"), "--print-plan", target,
         "/tmp/tree", "/tmp/build", "/tmp/inc", "/tmp/out"],
        cwd=ROOT, capture_output=True, text=True)
    if proc.returncode:
        raise AssertionError(proc.stderr)
    values = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


class RunE2E(unittest.TestCase):
    def test_every_target_has_one_plan(self):
        for name in NAMES:
            with self.subTest(target=name):
                doc = targets.load(name)
                values = plan(name)
                self.assertEqual(values["TARGET"], name)
                self.assertEqual(values["STRATEGY"], doc["strategy"])
                self.assertEqual(values["SOURCE"], doc["source"])
                self.assertEqual(values["FEATURES"], doc["features"])
                self.assertEqual(values["AXES"], doc["axes"] or "")
                self.assertEqual(values["BUILDER"], doc["runner"]["builder"])
                self.assertEqual(values["EXPECTED_QUERIES"],
                                 str(doc["diff_policy"]["expected_queries"]))
                self.assertEqual(values["ALLOW_REF_ASSERTS"],
                                 "" if doc["diff_policy"]["allow_ref_asserts"]
                                 is None else
                                 str(doc["diff_policy"]["allow_ref_asserts"]))
                self.assertEqual(values["EXPECT_UNANSWERABLE"],
                                 "" if doc["diff_policy"]["expect_unanswerable"]
                                 is None else
                                 str(doc["diff_policy"]["expect_unanswerable"]))

    def test_shims_are_thin(self):
        for name in NAMES:
            path = ROOT / ("run-%s-end-to-end.sh" % name)
            lines = path.read_text().splitlines()
            self.assertLessEqual(len(lines), 6, path.name)
            self.assertIn("run-e2e.sh", path.read_text())
        self.assertFalse((ROOT / "run-end-to-end.sh").exists())


if __name__ == "__main__":
    unittest.main()
