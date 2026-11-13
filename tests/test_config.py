"""`gisel-ab setup`: flag > environment > config file, and no exports."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gisel_ab import paths  # noqa: E402


def _shape(root: Path) -> tuple[Path, Path]:
    llvm = root / "llvm-project"
    (llvm / "llvm" / "include" / "llvm").mkdir(parents=True)
    build = root / "build"
    build.mkdir()
    (build / "build.ninja").write_text("")
    evidence = root / "evidence"
    evidence.mkdir()
    (evidence / "EVIDENCE.json").write_text("{}\n")
    return llvm, build


def run_setup(*args, env=None):
    base = {k: v for k, v in os.environ.items()
            if k not in ("AB_TREE", "AB_BUILD", "GISEL_AB_EVIDENCE")}
    base.update(env or {})
    return subprocess.run([sys.executable, str(ROOT / "ab.py"), "setup", *args],
                          cwd=ROOT, env=base, capture_output=True, text=True)


class Priority(unittest.TestCase):
    def test_flag_beats_environment_beats_config(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            flag = d / "flag"
            env_tree = d / "env"
            cfg_tree = d / "cfg"
            cfg = d / "config.json"
            cfg.write_text(json.dumps({"llvm": str(cfg_tree)}))
            with mock.patch.dict(os.environ, {
                    "GISEL_AB_CONFIG": str(cfg),
                    "AB_TREE": str(env_tree)}, clear=True):
                self.assertEqual(paths.locate_tree(str(flag)),
                                 (flag, "argument"))
                self.assertEqual(paths.locate_tree(),
                                 (env_tree, "AB_TREE"))
            with mock.patch.dict(os.environ,
                                 {"GISEL_AB_CONFIG": str(cfg)}, clear=True):
                found, where = paths.locate_tree()
                self.assertEqual(found, cfg_tree)
                self.assertEqual(where, str(cfg))

    def test_nothing_configured_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ,
                                 {"GISEL_AB_CONFIG": str(Path(d) / "none.json")},
                                 clear=True):
                self.assertEqual(paths.locate_tree(), (None, ""))
                self.assertEqual(paths.locate_build(), (None, ""))


class SetupCommand(unittest.TestCase):
    def test_it_writes_reads_and_unsets(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            llvm, build = _shape(d)
            cfg = d / "config.json"
            env = {"GISEL_AB_CONFIG": str(cfg)}
            done = run_setup("--llvm", str(llvm), "--build", str(build), env=env)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn("wrote %s" % cfg, done.stdout)
            doc = json.loads(cfg.read_text())
            self.assertEqual(doc["llvm"], str(llvm.resolve()))
            self.assertEqual(doc["build"], str(build.resolve()))

            shown = run_setup("--show", env=env)
            self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
            self.assertIn("effective tree:", shown.stdout)
            self.assertIn(str(llvm.resolve()), shown.stdout)

            off = run_setup("--unset", "build", env=env)
            self.assertEqual(off.returncode, 0, off.stderr)
            self.assertNotIn("build", json.loads(cfg.read_text()))

    def test_an_invalid_directory_is_an_input_error(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cfg = d / "config.json"
            done = run_setup("--llvm", str(d / "nope"),
                             env={"GISEL_AB_CONFIG": str(cfg)})
            self.assertEqual(done.returncode, 2, done.stdout)
            self.assertIn("not an llvm-project checkout", done.stderr)
            self.assertFalse(cfg.exists())

    def test_no_arguments_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as d:
            done = run_setup(env={"GISEL_AB_CONFIG": str(Path(d) / "c.json")})
            self.assertEqual(done.returncode, 2)
            self.assertIn("nothing to do", done.stderr)

    def test_evidence_default_follows_the_config(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cfg = d / "config.json"
            cfg.write_text(json.dumps({"evidence": str(d / "ev")}))
            with mock.patch.dict(os.environ,
                                 {"GISEL_AB_CONFIG": str(cfg)}, clear=True):
                from gisel_ab import evidence
                self.assertEqual(evidence.default_manifest(),
                                 d / "ev" / "EVIDENCE.json")


if __name__ == "__main__":
    unittest.main()
