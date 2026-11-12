"""RELEASE.json must describe the corpus that actually shipped."""

from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GISEL = Path(os.environ.get("GISEL_SRC") or ROOT.parent / "gisel")
CORPUS = Path(os.environ.get("GISEL_CORPUS") or GISEL / "tests" / "corpus")
MANIFEST = ROOT / "RELEASE.json"


class ReleaseManifest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MANIFEST.is_file(), "RELEASE.json is missing")
        self.data = json.loads(MANIFEST.read_text())

    def test_every_repo_commit_is_a_full_sha(self):
        for name, commit in self.data["repos"].items():
            self.assertEqual(len(commit), 40, name)
            int(commit, 16)

    def test_corpus_hashes_match_the_checkout(self):
        self.assertEqual(len(self.data["corpus_sha256"]), 9)
        for name, want in self.data["corpus_sha256"].items():
            data = (CORPUS / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), want, name)

    def test_the_golden_manifests_are_named(self):
        self.assertEqual(set(self.data["cases_sha256"]), {
            "x86.cases.jsonl", "aarch64.cases.jsonl", "riscv.cases.jsonl"})
        self.assertEqual(len(self.data["graph_goldens_sha256"]), 4)
        self.assertEqual(len(self.data["nightly_graphs_sha256"]), 5)
        self.assertEqual(len(self.data["pin"]["official_base_files"]), 12)


if __name__ == "__main__":
    unittest.main()
