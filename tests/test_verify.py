"""`ab.py verify` and the sha formatting around targets with no baseline inc.

M68k and RISCV have no generated baseline `.inc`: the official constructor
lives inside the library.  Every message that sliced `inc_sha256` used to
crash on those targets -- in `--dry-run`, and in the "baseline inc changed"
error path.  A harness that dies while reporting must be as broken as one
that reports the wrong thing.
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ab_harness", ROOT / "ab.py")
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)

M68K = json.loads((ROOT / "targets" / "m68k.json").read_text())


class ShaPrefix(unittest.TestCase):
    def test_none_prints_none_not_a_type_error(self):
        self.assertEqual(ab._sha_prefix(None), "none")
        self.assertEqual(ab._sha_prefix(None, 16), "none")

    def test_a_real_sha_is_truncated(self):
        self.assertEqual(ab._sha_prefix("a" * 64), "a" * 12)
        self.assertEqual(ab._sha_prefix("a" * 64, 16), "a" * 16)


class VerifyWithoutABaselineInc(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.tree = root / "tree"
        self.build = root / "build"
        self.state = root / "state"
        (self.tree / "llvm").mkdir(parents=True)
        lib = self.build / M68K["library"]
        lib.parent.mkdir(parents=True)
        lib.write_bytes(b"official library")
        subprocess.run(["git", "init", "-q", str(self.tree)], check=True)
        subprocess.run(["git", "-C", str(self.tree), "-c", "user.email=a@b",
                        "-c", "user.name=t", "commit", "-q", "--allow-empty",
                        "-m", "x"], check=True)
        self.lib = lib
        (self.state / "baseline").mkdir(parents=True)
        self.prov = self.state / "baseline" / "provenance.json"

    def _verify(self):
        return subprocess.run(
            [sys.executable, str(ROOT / "ab.py"), "verify",
             "--target", "m68k", "--tree", str(self.tree),
             "--build", str(self.build), "--state", str(self.state)],
            cwd=ROOT, capture_output=True, text=True)

    def _record(self, sha):
        self.prov.write_text(json.dumps({"inc_sha256": None,
                                         "lib_sha256": sha,
                                         "git_head": "0" * 40,
                                         "tree": str(self.tree),
                                         "build": str(self.build)}))

    def test_a_matching_library_is_a_pass(self):
        self._record(ab.sha256(self.lib))
        done = self._verify()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("OK", done.stdout)
        self.assertIn("lib=", done.stdout)

    def test_a_rebuilt_library_is_a_mismatch(self):
        self._record("0" * 64)
        done = self._verify()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("MISMATCH", done.stdout)

    def test_a_missing_library_is_an_input_error(self):
        self._record(ab.sha256(self.lib))
        self.lib.unlink()
        done = self._verify()
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("baseline library not found", done.stderr)


class BaselineChangeMessage(unittest.TestCase):
    def test_a_null_inc_does_not_crash_the_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = root / "tree"
            build = root / "build"
            state = root / "state"
            (tree / "llvm").mkdir(parents=True)
            build.mkdir()
            state.mkdir()
            subprocess.run(["git", "init", "-q", str(tree)], check=True)
            subprocess.run(["git", "-C", str(tree), "-c", "user.email=a@b",
                            "-c", "user.name=t", "commit", "-q", "--allow-empty",
                            "-m", "x"], check=True)
            base = state / "baseline"
            base.mkdir()
            (base / "provenance.json").write_text(json.dumps({
                "inc_sha256": "deadbeef" * 5, "lib_sha256": None,
                "git_head": ab.git_head(tree), "tree": str(tree),
                "build": str(build)}))
            with self.assertRaises(ab.HarnessError) as caught:
                ab.ensure_baseline(M68K, tree, build, state)
        message = str(caught.exception)
        self.assertIn("baseline inc changed", message)
        self.assertIn("none", message)


if __name__ == "__main__":
    unittest.main()
