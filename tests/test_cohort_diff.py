"""`cohort diff` reads two tags; it must not need either record to exist."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gisel_ab import cohort  # noqa: E402


def write(root, name, payload):
    path = root / name
    path.write_text(json.dumps(payload, sort_keys=True))


def commit(root, message):
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t",
                    "-c", "user.email=t@example.invalid", "commit", "-qm",
                    message], check=True)


class CohortDiff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

        write(self.root, "RELEASE.json", {
            "cohort": "cohort-old", "version": "1.0",
            "repos": {"ab": "a" * 40, "gisel": "b" * 40,
                      "upstream_source": "c" * 40},
            "pin": "pin-old",
            "corpus_sha256": {"X.gisel": "1"},
            "cases_sha256": {"x86.cases.jsonl": "1"},
            "graph_goldens_sha256": {"x86.json": "1"},
            "nightly_graphs_sha256": {"wasm.json": "1"},
        })
        write(self.root, "EVIDENCE.json", {"entries": [
            {"id": "G/x86", "artifacts": {"diff.json": "1"}},
            {"id": "U/x86", "artifacts": {"universe.jsonl": "1"}},
        ]})
        commit(self.root, "old release")
        subprocess.run(["git", "-C", str(self.root), "tag", "cohort-old"],
                       check=True)
        write(self.root, "VERIFICATION.json", {
            "cohort": "cohort-old",
            "gates": [
                {"name": "g1", "rc": 0, "command": "run g1",
                 "blobs": {"gisel:a.py": "1"}},
                {"name": "g2", "rc": 0, "command": "run g2",
                 "blobs": {"ab:b.py": "1"}},
            ],
        })
        commit(self.root, "record old")

        write(self.root, "RELEASE.json", {
            "cohort": "cohort-new", "version": "1.0",
            "repos": {"ab": "d" * 40, "gisel": "e" * 40,
                      "upstream_source": "c" * 40},
            "pin": "pin-old",
            "corpus_sha256": {"X.gisel": "2"},
            "cases_sha256": {"x86.cases.jsonl": "1"},
            "graph_goldens_sha256": {"x86.json": "1"},
            "nightly_graphs_sha256": {"wasm.json": "1"},
        })
        write(self.root, "EVIDENCE.json", {"entries": [
            {"id": "G/x86", "artifacts": {"diff.json": "2"}},
            {"id": "U/x86", "artifacts": {"universe.jsonl": "1"}},
            {"id": "G/riscv", "artifacts": {"diff.json": "3"}},
        ]})
        commit(self.root, "new release")
        subprocess.run(["git", "-C", str(self.root), "tag", "cohort-new"],
                       check=True)
        write(self.root, "VERIFICATION.json", {
            "cohort": "cohort-new",
            "gates": [
                {"name": "g1", "rc": 0, "command": "run g1",
                 "blobs": {"gisel:a.py": "2"}},
                {"name": "g2", "rc": 1, "command": "run g2 suffix",
                 "blobs": {"ab:b.py": "1"}},
            ],
        })
        commit(self.root, "record new")

    def tearDown(self):
        self.tmp.cleanup()

    def test_delta_covers_release_gates_blobs_and_evidence(self):
        data = cohort.diff_cohorts("cohort-new", "cohort-old", self.root)
        self.assertEqual(data["commits"]["added"], [])
        self.assertEqual(sorted(data["commits"]["changed"]),
                         ["ab", "gisel"])
        self.assertEqual(data["hashes"]["corpus_sha256"]["changed"],
                         {"X.gisel": {"old": "1", "new": "2"}})
        self.assertEqual(data["gates"]["rc_changed"],
                         [{"name": "g2", "old": 0, "new": 1}])
        self.assertEqual(data["gates"]["command_changed"], ["g2"])
        self.assertEqual(sorted(data["blobs"]["changed"]),
                         ["gisel:a.py"])
        self.assertEqual(data["evidence"]["added"], ["G/riscv"])
        self.assertEqual(data["evidence"]["changed"],
                         {"G/x86": {"old": json.dumps({"diff.json": "1"},
                                                      sort_keys=True),
                                    "new": json.dumps({"diff.json": "2"},
                                                      sort_keys=True)}})
        self.assertIsNotNone(data["new"]["record"])
        self.assertIsNotNone(data["old"]["record"])

    def test_missing_tag_is_an_error_not_a_difference(self):
        with self.assertRaises(cohort.DiffError):
            cohort.diff_cohorts("cohort-new", "cohort-nope", self.root)

    def test_a_tag_without_its_record_still_compares_the_frozen_files(self):
        # A tag is cut before its record commit exists.  The old record stays
        # reachable in history; the new one is absent, and that is `None`,
        # not "no difference".
        subprocess.run(["git", "-C", str(self.root), "reset", "-q", "--hard",
                        "cohort-new"], check=True)
        data = cohort.diff_cohorts("cohort-new", "cohort-old", self.root)
        self.assertIsNone(data["new"]["record"])
        self.assertIsNotNone(data["old"]["record"])
        self.assertEqual(data["gates"]["new"], 0)
        self.assertEqual(data["evidence"]["added"], ["G/riscv"])


if __name__ == "__main__":
    unittest.main()
