"""closure.py: successor construction and the fixed-point loop."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GISEL = Path(os.environ.get("GISEL_SRC") or ROOT.parent / "gisel")
SCRIPT = [sys.executable, "-m", "gisel_ab.l0.closure"]

RUNNER = '''\
#!/usr/bin/env python3
import argparse, json
ap = argparse.ArgumentParser()
ap.add_argument("--queries", required=True)
a = ap.parse_args()
STEP = {"s8": "s16", "s16": "s32"}
MODE = "__MODE__"
for line in open(a.queries):
    q = json.loads(line)
    ty = q["types"][0]
    if MODE == "disagree" and ty == "s8":
        q.update(action="Legal", type_idx=0, new_type="LLT_invalid")
    elif MODE == "stuck":
        q.update(action="WidenScalar", type_idx=0, new_type=ty)
    elif ty in STEP:
        q.update(action="WidenScalar", type_idx=0, new_type=STEP[ty])
    else:
        q.update(action="Legal", type_idx=0, new_type="LLT_invalid")
    print(json.dumps(q))
'''


def row(name, types):
    return {"config": "C0", "name": name, "types": types, "mem": None,
            "imms": []}


@unittest.skipUnless(GISEL.is_dir(), "gisel checkout is not next to ab")
class Unit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(GISEL.parent))
        import closure
        cls.c = closure

    def test_terminal_actions_stop(self):
        for action in ("Legal", "Lower", "Libcall", "Custom", "Unsupported"):
            follow, why = self.c.successor(
                row("G_ADD", ["s8"]),
                {"action": action, "type_idx": 0, "new_type": "s16"})
            self.assertIsNone(follow)
            self.assertEqual(why, "terminal")

    def test_mutation_becomes_the_next_query(self):
        follow, why = self.c.successor(
            row("G_LOAD", ["s8", "p0:*"]),
            {"action": "WidenScalar", "type_idx": 0, "new_type": "s16"})
        self.assertIsNone(why)
        self.assertEqual(follow["types"], ["s16", "p0:*"])
        self.assertEqual(follow["mem"], None)

    def test_stuck_is_not_a_successor(self):
        follow, why = self.c.successor(
            row("G_ADD", ["s32"]),
            {"action": "WidenScalar", "type_idx": 0, "new_type": "s32"})
        self.assertIsNone(follow)
        self.assertEqual(why, "stuck")

    def test_unanswerable_has_no_successor(self):
        follow, why = self.c.successor(
            row("G_ADD", ["s8"]), {"status": "unanswerable"})
        self.assertIsNone(follow)
        self.assertEqual(why, "unanswerable")


class Loop(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.seed = self.dir / "seed.jsonl"
        with self.seed.open("w") as handle:
            for r in (row("G_ADD", ["s8"]), row("G_SUB", ["s32"])):
                handle.write(json.dumps(r) + "\n")

    def runner(self, mode):
        path = self.dir / ("runner-%s" % mode)
        path.write_text(RUNNER.replace("__MODE__", mode))
        path.chmod(0o755)
        return path

    def run_closure(self, ref, ours, *extra):
        out = self.dir / "out"
        proc = subprocess.run(
            [*SCRIPT, "--target", "x86",
             "--seed", str(self.seed), "--official", str(ref),
             "--ours", str(ours), "--out", str(out), *extra],
            capture_output=True, text=True)
        report = json.loads((out / "closure.json").read_text())
        return proc, report

    def test_fixed_point_adds_the_widened_states(self):
        runner = self.runner("same")
        proc, report = self.run_closure(runner, runner)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(report["states"], {"seed": 2, "total": 4, "added": 2})
        self.assertEqual(report["edges"]["successors"], 2)
        self.assertEqual(report["edges"]["revisited"], 0)
        self.assertEqual([r["asked"] for r in report["rounds"]], [2, 1, 1])

    def test_disagreement_stops_the_run(self):
        proc, report = self.run_closure(self.runner("same"),
                                        self.runner("disagree"))
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(report["disagree"])

    def test_a_successor_that_was_already_asked_is_revisited(self):
        with self.seed.open("w") as handle:
            for r in (row("G_ADD", ["s8"]), row("G_ADD", ["s16"])):
                handle.write(json.dumps(r) + "\n")
        runner = self.runner("same")
        proc, report = self.run_closure(runner, runner)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(report["edges"]["revisited"], 1)
        self.assertEqual(report["states"]["added"], 1)

    def test_stuck_is_counted_not_followed(self):
        runner = self.runner("stuck")
        proc, report = self.run_closure(runner, runner)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(report["edges"]["stuck"], 2)
        self.assertEqual(report["states"]["added"], 0)


if __name__ == "__main__":
    unittest.main()
