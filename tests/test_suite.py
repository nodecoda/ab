"""`suite.py`: the offline check of our rules against a frozen snapshot.

Three properties matter and none of them is "it passes on m68k":

1. a snapshot whose sha no longer matches is refused (data drift is not a
   rule difference),
2. a snapshot that really disagrees returns rc=1 with the key named,
3. the check runs no LLVM -- the corpus is the only input.
"""

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ab_suite", ROOT / "suite.py")
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)

M68K = ROOT / "suite" / "m68k"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class TheFrozenM68kSuite(unittest.TestCase):
    def test_it_agrees(self):
        result = suite.check("m68k")
        self.assertEqual(result["query_count"], 35)
        self.assertEqual(result["disagree"], 0, result["first"][:3])
        self.assertEqual(result["agree"], 35)
        self.assertEqual(result["unanswerable"], 0)

    def test_it_needs_no_llvm(self):
        # The check shells out to gisel twice and reads three files; if it
        # ever grew a compiler dependency this would fail on PATH.
        done = subprocess.run(
            [sys.executable, str(ROOT / "suite.py"), "check", "--target",
             "m68k"],
            cwd=ROOT, capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("agree=35", done.stdout)

    def test_the_manifest_pins_every_input(self):
        doc = json.loads((M68K / "suite.json").read_text())
        self.assertRegex(doc["pin"], r"^[0-9a-f]{40}$")
        self.assertRegex(doc["official_base"], r"^[0-9a-f]{40}$")
        self.assertEqual(sha(M68K / doc["queries"]), doc["queries_sha256"])
        self.assertEqual(sha(M68K / doc["answers"]), doc["answers_sha256"])


class RefuseThenReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "suite" / "tiny"
        self.root.mkdir(parents=True)
        shutil.copyfile(M68K / "queries.jsonl", self.root / "queries.jsonl")
        shutil.copyfile(M68K / "official.answers.jsonl",
                        self.root / "official.answers.jsonl")
        self.doc = json.loads((M68K / "suite.json").read_text())
        self.doc["corpus"] = str((M68K / self.doc["corpus"]).resolve())
        self.doc["features"] = str((M68K / self.doc["features"]).resolve())
        self._write()
        self.saved = suite.SUITE
        suite.SUITE = Path(self.tmp.name) / "suite"
        self.addCleanup(setattr, suite, "SUITE", self.saved)

    def _write(self):
        self.doc["queries_sha256"] = sha(self.root / "queries.jsonl")
        self.doc["answers_sha256"] = sha(self.root / "official.answers.jsonl")
        (self.root / "suite.json").write_text(json.dumps(self.doc))

    def test_a_stale_sha_is_refused(self):
        self.doc["answers_sha256"] = "0" * 64
        (self.root / "suite.json").write_text(json.dumps(self.doc))
        with self.assertRaises(suite.SuiteError) as caught:
            suite.check("tiny")
        self.assertIn("drifted", str(caught.exception))

    def test_a_corpus_that_moved_is_refused(self):
        self.doc["corpus_sha256"] = "0" * 64
        self._write()
        with self.assertRaises(suite.SuiteError) as caught:
            suite.check("tiny")
        self.assertIn("changed since the snapshot", str(caught.exception))

    def test_a_real_disagreement_is_reported_not_hidden(self):
        path = self.root / "official.answers.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for row in rows:
            if row["action"] == "Legal":
                row["action"] = "Unsupported"
                break
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self._write()
        result = suite.check("tiny")
        self.assertGreater(result["disagree"], 0)
        shown = repr(result["first"])
        self.assertIn("Legal", shown)
        self.assertIn("Unsupported", shown)


if __name__ == "__main__":
    unittest.main()
