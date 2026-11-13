"""The importer's denominator must describe the corpus that ships."""

from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GISEL = Path(os.environ.get("GISEL_SRC") or ROOT.parent / "gisel")
CORPUS = Path(os.environ.get("GISEL_CORPUS") or GISEL / "tests" / "corpus")
REPORT = CORPUS / "import-report.json"


class ImportReportTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            REPORT.is_file(),
            "%s is missing; run `upstream-source/importer/import-cxx.py --all`"
            % REPORT)
        self.report = json.loads(REPORT.read_text())

    def test_every_shipped_corpus_has_an_entry(self):
        shipped = {p.name for p in CORPUS.glob("*LegalizerInfo.gisel")}
        described = {entry["corpus_name"]
                     for entry in self.report["targets"].values()}
        self.assertEqual(shipped, described)

    def test_corpus_hash_matches_the_shipped_bytes(self):
        for name, entry in self.report["targets"].items():
            data = (CORPUS / entry["corpus_name"]).read_bytes()
            self.assertEqual(entry["corpus_sha256"],
                             hashlib.sha256(data).hexdigest(), name)

    def test_no_target_drifted_from_the_pin(self):
        for name, entry in self.report["targets"].items():
            self.assertFalse(entry.get("drift"), name)
            self.assertEqual(entry["rules"], entry["pinned"]["rules"], name)
            self.assertEqual(entry["rulesets"], entry["pinned"]["rulesets"], name)

    def test_refusals_are_counted_in_full(self):
        for name, entry in self.report["targets"].items():
            self.assertEqual(entry["counts"]["refused"],
                             len(entry["refused"]), name)
            self.assertEqual(entry["counts"]["skipped"], len(entry["skipped"]), name)
            self.assertEqual(entry["counts"]["ignored"], len(entry["ignored"]), name)


if __name__ == "__main__":
    unittest.main()
