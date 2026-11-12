"""The C++ runner's half of the protocol: answer lines, then rc=2 on a bad one.

This needs a built runner, which CI does not have.  Point AB_RUNNER at one
(`build-query-runner.sh` produces it) and the test runs; otherwise it skips.
The harness side of the same protocol (a half-written line, a non-signal
exit) is covered by test_run_queries.py with a fake runner.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RUNNER = os.environ.get("AB_RUNNER")
CONFIG = os.environ.get("AB_RUNNER_CONFIG", "C0")


def query(name="G_ADD", types=None, config=CONFIG):
    return {"config": config, "name": name,
            "types": types or ["s32", "s32"], "imms": []}


@unittest.skipUnless(RUNNER, "set AB_RUNNER to a built query runner")
class RunnerProtocol(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="runner-protocol-"))
        self.queries = self.dir / "queries.jsonl"

    def run_lines(self, lines):
        self.queries.write_text("".join(line + "\n" for line in lines))
        return subprocess.run([RUNNER, "--queries", str(self.queries)],
                              capture_output=True, text=True, timeout=120)

    def answers(self, stdout):
        return [json.loads(line) for line in stdout.splitlines() if line.strip()]

    def test_valid_queries_get_one_answer_each(self):
        found = self.run_lines([json.dumps(query()), json.dumps(query())])
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertEqual(len(self.answers(found.stdout)), 2)

    def test_bad_llt_stops_with_rc_two_and_keeps_prior_answers(self):
        self.queries.write_text(json.dumps(query()) + "\n"
                                + json.dumps(query(types=["not-an-llt"])) + "\n")
        found = subprocess.run([RUNNER, "--queries", str(self.queries)],
                               capture_output=True, text=True, timeout=120)
        self.assertEqual(found.returncode, 2, found.stderr)
        self.assertEqual(len(self.answers(found.stdout)), 1)

    def test_bad_json_stops_with_rc_two(self):
        found = self.run_lines([json.dumps(query()), "{"])
        self.assertEqual(found.returncode, 2, found.stderr)
        self.assertEqual(len(self.answers(found.stdout)), 1)

    def test_missing_query_file_is_rc_two(self):
        found = subprocess.run(
            [RUNNER, "--queries", str(self.dir / "absent.jsonl")],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(found.returncode, 2)


if __name__ == "__main__":
    unittest.main()
