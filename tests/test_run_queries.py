"""run-queries must not keep the half-written line of a crashing runner."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "run-queries.py"

FAKE = '''#!/usr/bin/env python3
import json
import os
import signal
import sys

path = sys.argv[sys.argv.index("--queries") + 1]
crash_on = os.environ.get("CRASH_ON")
exit_on = os.environ.get("EXIT_ON")
partial = os.environ.get("PARTIAL", '{"config": "C0", "na')

with open(path) as stream:
    queries = [json.loads(line) for line in stream if line.strip()]

for index, query in enumerate(queries):
    if exit_on is not None and query["types"][0] == exit_on:
        sys.stderr.write("fake runner cannot continue\\n")
        sys.stderr.flush()
        sys.exit(int(os.environ.get("EXIT_CODE", "3")))
    if query["types"][0] == crash_on:
        sys.stdout.write(partial)
        sys.stdout.flush()
        sys.stderr.write(os.environ.get("ASSERT_TEXT", ""))
        sys.stderr.flush()
        os.kill(os.getpid(), signal.SIGABRT)
    answer = dict(query)
    answer.update({"action": "Legal", "type_idx": 0,
                   "new_type": "LLT_invalid"})
    sys.stdout.write(json.dumps(answer) + "\\n")
    sys.stdout.flush()
'''


class RunQueries(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="runq-"))
        self.runner = self.dir / "fake-runner"
        self.runner.write_text(FAKE)
        self.runner.chmod(0o755)
        self.queries = self.dir / "queries.jsonl"
        rows = [{"config": "C0", "name": "G_ADD", "types": ["s%d" % (i + 1)],
                 "mem": None, "imms": []} for i in range(5)]
        self.queries.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.rows = rows

    def invoke(self, crash_on=None, assert_text="", exit_on=None,
               exit_code=3, expect_rc=0):
        out = self.dir / "out.jsonl"
        report = self.dir / "report.json"
        env = dict(os.environ, CRASH_ON=crash_on or "", ASSERT_TEXT=assert_text,
                   EXIT_ON=exit_on or "", EXIT_CODE=str(exit_code))
        proc = subprocess.run([sys.executable, str(RUN), str(self.runner),
                               str(self.queries), str(out),
                               "--report", str(report)],
                              check=False, env=env, capture_output=True,
                              text=True)
        self.assertEqual(proc.returncode, expect_rc, proc.stderr)
        text = out.read_text().splitlines()
        parsed = []
        for line in text:
            parsed.append(json.loads(line))  # must all be complete JSON
        return parsed

    def invoke_with_report(self, **kwargs):
        rows = self.invoke(**kwargs)
        return rows, json.loads((self.dir / "report.json").read_text())

    def test_partial_answer_is_dropped_and_the_crasher_is_marked(self):
        rows = self.invoke(crash_on="s3")
        self.assertEqual(len(rows), len(self.rows))
        self.assertEqual(rows[2].get("status"), "unanswerable")
        self.assertEqual(rows[2].get("reason"), "asserted")
        # Answers before and after the crash stay aligned with their queries.
        self.assertEqual(rows[0]["types"], ["s1"])
        self.assertEqual(rows[0]["action"], "Legal")
        self.assertEqual(rows[1]["types"], ["s2"])
        self.assertEqual(rows[3]["types"], ["s4"])
        self.assertEqual(rows[3]["action"], "Legal")
        self.assertEqual(rows[4]["types"], ["s5"])

    def test_a_runner_that_dies_before_answering_marks_the_first_query(self):
        rows = self.invoke(crash_on="s1")
        self.assertEqual(rows[0].get("status"), "unanswerable")
        self.assertEqual(rows[1]["types"], ["s2"])
        self.assertEqual(rows[1]["action"], "Legal")

    def test_the_assert_site_survives_the_restart(self):
        """A crash the in-process handler never saw still names its site."""
        rows = self.invoke(
            crash_on="s3",
            assert_text="llc: /t/llvm/lib/X/Foo.cpp:42: Assertion `p' failed.\n")
        self.assertEqual(rows[2]["assert_site"], "Foo.cpp:42")

    def test_an_unreachable_is_recorded_too(self):
        rows = self.invoke(
            crash_on="s3",
            assert_text="UNREACHABLE executed at /t/llvm/lib/Y/Bar.h:151!\n")
        self.assertEqual(rows[2]["assert_site"], "Bar.h:151")

    def test_a_non_signal_exit_is_rc_two_and_still_writes_answers(self):
        """A3: an infrastructure failure must not look like a clean run."""
        rows, report = self.invoke_with_report(exit_on="s3", exit_code=3,
                                              expect_rc=2)
        self.assertEqual(len(rows), len(self.rows))
        self.assertEqual(rows[1]["action"], "Legal")
        for index in (2, 3, 4):
            self.assertEqual(rows[index]["status"], "unanswerable")
            self.assertEqual(rows[index]["reason"], "runner-error")
        self.assertEqual(report["answered"], 2)
        self.assertEqual(report["failed_at"], 3)
        self.assertEqual(report["failed_queries"], 3)
        self.assertIn("exit 3 on query 3", report["error"])

    def test_an_unreadable_runner_is_rc_two(self):
        out = self.dir / "out.jsonl"
        proc = subprocess.run([sys.executable, str(RUN),
                               str(self.dir / "no-such-runner"),
                               str(self.queries), str(out)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("run-queries:", proc.stderr)

    def test_a_complete_answer_before_the_crash_is_kept(self):
        rows = self.invoke(crash_on="s5")
        self.assertEqual(rows[3]["action"], "Legal")
        self.assertEqual(rows[3]["types"], ["s4"])
        self.assertEqual(rows[4].get("status"), "unanswerable")


if __name__ == "__main__":
    unittest.main()
