"""RELEASE.json must describe the corpus that actually shipped."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GISEL = Path(os.environ.get("GISEL_SRC") or ROOT.parent / "gisel")
CORPUS = Path(os.environ.get("GISEL_CORPUS") or GISEL / "tests" / "corpus")
MANIFEST = ROOT / "RELEASE.json"


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True)


class ReleaseManifest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MANIFEST.is_file(), "RELEASE.json is missing")
        self.data = json.loads(MANIFEST.read_text())

    def test_every_repo_commit_is_a_full_sha(self):
        for name, commit in self.data["repos"].items():
            self.assertEqual(len(commit), 40, name)
            int(commit, 16)

    def test_ab_entry_names_the_commit_before_the_manifest(self):
        """A manifest cannot name the commit that adds it.

        `repos.ab` is the commit the evidence was built at; the manifest
        commit adds only this file, so the recorded commit must be its
        parent.  Any later commit that edits RELEASE.json moves the pair.
        """
        found = git("log", "-1", "--format=%H", "--", "RELEASE.json")
        self.assertEqual(found.returncode, 0, found.stderr)
        manifest_commit = found.stdout.strip()
        self.assertTrue(manifest_commit, "RELEASE.json is not committed")
        parent = git("rev-parse", manifest_commit + "^")
        self.assertEqual(parent.returncode, 0, parent.stderr)
        self.assertEqual(self.data["repos"]["ab"], parent.stdout.strip())

    def test_repo_entries_are_ancestors(self):
        ab = git("merge-base", "--is-ancestor", self.data["repos"]["ab"], "HEAD")
        self.assertEqual(ab.returncode, 0, "repos.ab is not an ancestor of HEAD")
        gisel = Path(os.environ.get("GISEL_SRC") or ROOT.parent / "gisel")
        if (gisel / ".git").exists():
            commit = self.data["repos"]["gisel"]
            found = subprocess.run(
                ["git", "-C", str(gisel), "cat-file", "-e", commit + "^{commit}"],
                capture_output=True, text=True)
            self.assertEqual(found.returncode, 0,
                             "gisel checkout does not contain %s" % commit[:12])

    def test_version_matches_the_package(self):
        self.assertEqual(self.data["version"], "0.3.0")
        init = GISEL / "gisel" / "__init__.py"
        if init.exists():
            match = re.search(r'__version__ = "([^"]+)"', init.read_text())
            self.assertIsNotNone(match)
            self.assertEqual(self.data["version"], match.group(1))

    def test_cohort_is_a_freeze_tag(self):
        self.assertTrue(self.data["cohort"].startswith("cohort-"),
                        "a `v*` cohort tag would publish to PyPI")
        self.assertNotIn(" ", self.data["cohort"])

    def test_corpus_hashes_match_the_checkout(self):
        self.assertEqual(len(self.data["corpus_sha256"]), 9)
        for name, want in self.data["corpus_sha256"].items():
            data = (CORPUS / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), want, name)

    def test_the_golden_manifests_are_named(self):
        self.assertEqual(set(self.data["cases_sha256"]), {
            "x86.cases.jsonl", "aarch64.cases.jsonl", "riscv.cases.jsonl",
            "arm.cases.jsonl", "mips.cases.jsonl", "ppc.cases.jsonl",
            "m68k.cases.jsonl", "wasm.cases.jsonl", "spirv.cases.jsonl"})
        self.assertEqual(len(self.data["graph_goldens_sha256"]), 4)
        self.assertEqual(len(self.data["nightly_graphs_sha256"]), 10)
        self.assertEqual(len(self.data["pin"]["official_base_files"]), 12)


if __name__ == "__main__":
    unittest.main()
