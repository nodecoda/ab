"""The negative-control wrappers must not call an input error "caught"."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GISEL = Path(os.environ.get("GISEL_SRC") or ROOT.parent / "gisel")

QUERY = {"config": "C0", "name": "G_ADD", "types": ["s32"], "mem": None,
         "imms": [], "ruleset": "X_G_ADD"}
OFFICIAL = dict(QUERY, action="Legal", type_idx=0, new_type="LLT_invalid")
OURS = dict(QUERY, action="Unsupported", type_idx=0, new_type="LLT_invalid")


def fake_end_to_end() -> str:
    template = '''#!/usr/bin/env bash
set -euo pipefail
if [[ -n ${FAKE_RECORD:-} ]]; then printf '%s|%s\\n' "$1" "$2" > "$FAKE_RECORD"; fi
out=${4:?}
mkdir -p "$out"
case ${FAKE_NEG_MODE:-caught} in
  blind) exit 0 ;;
  input) echo "broken input" >&2; exit 2 ;;
  nodiff) exit 1 ;;
  caught)
    printf '%s\\n' '__QUERY__' > "$out/queries.jsonl"
    printf '%s\\n' '__OFFICIAL__' > "$out/official.answers.jsonl"
    printf '%s\\n' '__OURS__' > "$out/ours.answers.jsonl"
    printf '{}\\n' > "$out/diff.json"
    exit 1 ;;
  *) echo "unknown mode" >&2; exit 2 ;;
esac
'''
    return (template.replace("__QUERY__", json.dumps(QUERY))
            .replace("__OFFICIAL__", json.dumps(OFFICIAL))
            .replace("__OURS__", json.dumps(OURS)))


def link(src: Path, dst: Path):
    dst.symlink_to(src)


class NegativeScripts(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ab-neg-"))
        for name in ("env.sh", "inject-missing-opcode.py", "diff.py",
                     "g-attribution.py", "u-attribution.py",
                     "run-g-negative.sh", "targets.py"):
            link(ROOT / name, self.dir / name)
        (self.dir / "run-x86-end-to-end.sh").write_text(fake_end_to_end())
        (self.dir / "run-x86-end-to-end.sh").chmod(0o755)
        self.tree = self.dir / "tree"
        (self.tree / "llvm" / "include" / "llvm").mkdir(parents=True)
        self.build = self.dir / "build"
        self.build.mkdir()
        (self.build / "build.ninja").write_text("")

    def run_g(self, mode):
        env = dict(os.environ, GISEL_SRC=str(GISEL), FAKE_NEG_MODE=mode)
        return subprocess.run(
            ["bash", str(self.dir / "run-g-negative.sh"), "x86", "G_ADD",
             str(self.dir / "out"), "--tree", str(self.tree),
             "--build", str(self.build)],
            cwd=self.dir, env=env, capture_output=True, text=True)

    def test_explicit_tree_and_build_reach_the_e2e_script(self):
        record = self.dir / "record.txt"
        env = dict(os.environ, GISEL_SRC=str(GISEL), FAKE_NEG_MODE="caught",
                   FAKE_RECORD=str(record))
        proc = subprocess.run(
            ["bash", str(self.dir / "run-g-negative.sh"), "x86", "G_ADD",
             str(self.dir / "out"), "--tree", str(self.tree),
             "--build", str(self.build)],
            cwd=self.dir, env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(record.read_text().strip(),
                         "%s|%s" % (self.tree, self.build))

    def test_blind_is_exit_one(self):
        proc = self.run_g("blind")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("control blind", proc.stderr)

    def test_input_error_is_exit_two(self):
        proc = self.run_g("input")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("input error", proc.stderr)
        self.assertNotIn(": caught", proc.stderr)

    def test_an_end_to_end_failure_without_a_diff_is_input_error(self):
        proc = self.run_g("nodiff")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("input error", proc.stderr)

    def test_a_real_disagreement_is_caught(self):
        proc = self.run_g("caught")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("caught", proc.stderr)
        attribution = json.loads(
            (self.dir / "out" / "run" / "attribution.json").read_text())
        self.assertEqual(attribution["disagree"], 1)
        self.assertEqual(attribution["by_ruleset"], {"X_G_ADD": 1})


if __name__ == "__main__":
    unittest.main()
