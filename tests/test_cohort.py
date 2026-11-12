"""The cohort record is only useful if it is re-checkable.

These tests do not run the real gates.  They pin the parts that decide
whether a gate is FRESH: the gate inventory, the content fingerprint, the
changed-input report, and the refusal to tag a dirty tree.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cohort

ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def init_repo(path: Path, files: dict[str, str]) -> str:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    for name, text in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "seed")
    return git(path, "rev-parse", "HEAD").stdout.strip()


class GateInventory(unittest.TestCase):
    def test_every_manifest_gate_has_a_descriptor(self):
        manifest = cohort.load_manifest()
        table = cohort.gate_table(manifest)
        self.assertEqual([g["manifest_command"] for g in table], manifest["gates"])
        for gate in table:
            self.assertIn(gate["repo"], cohort.REPO_DIRS)
            self.assertTrue(gate["inputs"], gate["name"])

    def test_online_plan_names_the_adopt_gate(self):
        manifest = cohort.load_manifest()
        table = cohort.gate_table(manifest, online=True)
        adopt = [g for g in table if g["name"] == "adopt-check"]
        self.assertEqual(len(adopt), 1)
        self.assertTrue(adopt[0]["online"])
        self.assertNotIn("adopt-check",
                         [g["name"] for g in cohort.gate_table(manifest)])


class Fingerprints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.gisel = self.root / "gisel"
        self.commit = init_repo(self.gisel, {
            "gisel/a.py": "A = 1\n",
            "gisel/b.py": "B = 1\n",
            "tests/corpus/X.gisel": "ruleset X: G_ADD\n",
        })
        self.gate = {"name": "unit", "repo": "gisel",
                     "inputs": ["gisel/*.py"]}
        self.patches = [
            mock.patch.object(cohort, "GISEL", self.gisel),
            mock.patch.object(cohort, "UPSTREAM", self.root / "upstream"),
            mock.patch.object(cohort, "AB", self.root / "ab"),
        ]
        for patch in self.patches:
            patch.start()
        cohort._CACHE.clear()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        cohort._CACHE.clear()
        self.tmp.cleanup()

    def test_committed_fingerprint_is_deterministic(self):
        first = cohort.fingerprint(self.gate, commits={"gisel": self.commit})
        cohort._CACHE.clear()
        second = cohort.fingerprint(self.gate, commits={"gisel": self.commit})
        self.assertEqual(first, second)

    def test_worktree_fingerprint_follows_content(self):
        before = cohort.fingerprint(self.gate, worktree=True)
        (self.gisel / "gisel" / "a.py").write_text("A = 2\n")
        cohort._CACHE.clear()
        after = cohort.fingerprint(self.gate, worktree=True)
        self.assertNotEqual(before, after)

    def test_glob_selects_the_expected_files(self):
        blobs = cohort._blob_map(self.gate, worktree=True)
        self.assertEqual(set(blobs), {"gisel:gisel/a.py", "gisel:gisel/b.py"})
        corpus = {"name": "cases", "repo": "gisel",
                  "inputs": ["tests/corpus/*.gisel"]}
        self.assertEqual(set(cohort._blob_map(corpus, worktree=True)),
                         {"gisel:tests/corpus/X.gisel"})

    def test_changed_inputs_names_the_file(self):
        record = {
            "commits": {"gisel": self.commit},
            "gates": [{"name": "unit",
                       "blobs": cohort._blob_map(self.gate, worktree=True)}],
        }
        self.assertEqual(cohort.changed_inputs(self.gate, record), [])
        (self.gisel / "gisel" / "b.py").write_text("B = 2\n")
        cohort._CACHE.clear()
        self.assertEqual(cohort.changed_inputs(self.gate, record),
                         ["gisel:gisel/b.py"])


class Tagging(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ab = self.root / "ab"
        self.gisel = self.root / "gisel"
        self.upstream = self.root / "upstream-source"
        self.gisel_commit = init_repo(self.gisel, {"gisel/a.py": "A = 1\n"})
        self.upstream_commit = init_repo(self.upstream, {"pin/PIN.json": "{}\n"})
        self.ab_commit = init_repo(self.ab, {"code.py": "x = 1\n"})
        (self.ab / "RELEASE.json").write_text(json.dumps({
            "schema": 1,
            "cohort": "cohort-test",
            "repos": {"gisel": self.gisel_commit,
                      "upstream_source": self.upstream_commit,
                      "ab": self.ab_commit},
            "gates": [],
        }, indent=2) + "\n")
        git(self.ab, "add", "RELEASE.json")
        git(self.ab, "commit", "-q", "-m", "manifest")
        self.manifest_commit = git(self.ab, "rev-parse", "HEAD").stdout.strip()
        self.patches = [
            mock.patch.object(cohort, "AB", self.ab),
            mock.patch.object(cohort, "GISEL", self.gisel),
            mock.patch.object(cohort, "UPSTREAM", self.upstream),
            mock.patch.object(cohort, "MANIFEST", self.ab / "RELEASE.json"),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def tag(self):
        args = mock.Mock(name="args")
        args.name = "cohort-test"
        args.push = False
        return cohort.cmd_tag(args)

    def test_clean_trio_is_tagged_at_the_recorded_commits(self):
        self.assertEqual(self.tag(), 0)
        for repo, expected in ((self.gisel, self.gisel_commit),
                               (self.upstream, self.upstream_commit),
                               (self.ab, self.manifest_commit)):
            got = git(repo, "rev-parse", "cohort-test^{commit}").stdout.strip()
            self.assertEqual(got, expected)

    def test_dirty_tree_is_refused(self):
        (self.gisel / "gisel" / "a.py").write_text("A = 2\n")
        self.assertEqual(self.tag(), 2)
        self.assertEqual(git(self.gisel, "tag", "--list").stdout.strip(), "")

    def test_existing_tag_is_not_rewritten(self):
        self.assertEqual(self.tag(), 0)
        git(self.gisel, "tag", "-d", "cohort-test")
        self.assertEqual(self.tag(), 2)


if __name__ == "__main__":
    unittest.main()
