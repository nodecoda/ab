"""The harness never defaults to a developer machine.

`paths.require_tree`/`require_build` are the single place that decides where
the LLVM checkout and build are.  A missing root must be an rc=2 input error
with an actionable message, not a FileNotFoundError halfway through a run or,
worse, a silent swap inside someone else's tree.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import paths

ROOT = Path(__file__).resolve().parents[1]


def make_tree(base: Path) -> Path:
    (base / "llvm" / "include" / "llvm").mkdir(parents=True)
    (base / ".git").write_text("gitdir: elsewhere\n")
    return base


def make_build(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "build.ninja").write_text("")
    return base


class RequireTree(unittest.TestCase):
    def run_require(self, fn, *args):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            try:
                return fn(*args), err.getvalue()
            except SystemExit as exc:
                return exc.code, err.getvalue()

    def test_missing_is_rc2_with_a_fix(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            code, err = self.run_require(paths.require_tree)
        self.assertEqual(code, 2)
        self.assertIn("AB_TREE", err)
        self.assertIn("export AB_TREE=", err)

    def test_env_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_tree(Path(tmp))
            with mock.patch.dict(os.environ, {"AB_TREE": tmp}, clear=True):
                got, _ = self.run_require(paths.require_tree)
        self.assertEqual(got, Path(tmp).resolve())

    def test_cohort_tree_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_tree(Path(tmp))
            with mock.patch.dict(os.environ, {"COHORT_TREE": tmp}, clear=True):
                got, _ = self.run_require(paths.require_tree)
        self.assertEqual(got, Path(tmp).resolve())

    def test_explicit_beats_env(self):
        with tempfile.TemporaryDirectory() as a, \
                tempfile.TemporaryDirectory() as b:
            make_tree(Path(a))
            make_tree(Path(b))
            with mock.patch.dict(os.environ, {"AB_TREE": a}, clear=True):
                got, _ = self.run_require(paths.require_tree, b)
        self.assertEqual(got, Path(b).resolve())

    def test_wrong_shape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, err = self.run_require(paths.require_tree, tmp)
        self.assertEqual(code, 2)
        self.assertIn("does not look like", err)


class RequireBuild(unittest.TestCase):
    def test_missing_is_rc2_with_a_fix(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                paths.require_build()
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("AB_BUILD", err.getvalue())

    def test_env_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_build(Path(tmp))
            with mock.patch.dict(os.environ, {"AB_BUILD": tmp}, clear=True):
                self.assertEqual(paths.require_build(), Path(tmp).resolve())

    def test_cmake_cache_counts_as_a_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "CMakeCache.txt").write_text("")
            with mock.patch.dict(os.environ, {"AB_BUILD": tmp}, clear=True):
                self.assertEqual(paths.require_build(), Path(tmp).resolve())

    def test_wrong_shape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    paths.require_build(tmp)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("does not look like", err.getvalue())


class LlvmRepo(unittest.TestCase):
    def test_fallback_is_used_when_env_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_tree(Path(tmp))
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(paths.llvm_repo(fallback=tmp),
                                 Path(tmp).resolve())

    def test_missing_without_fallback_is_rc2(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                paths.llvm_repo()
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("COHORT_LLVM", err.getvalue())


class ScriptsRefuseMissingRoots(unittest.TestCase):
    def clean_env(self):
        drop = {"AB_TREE", "AB_BUILD", "COHORT_TREE", "COHORT_LLVM"}
        return {k: v for k, v in os.environ.items() if k not in drop}

    def test_run_g_negative_without_roots(self):
        with tempfile.TemporaryDirectory() as out:
            done = subprocess.run(
                ["bash", str(ROOT / "run-g-negative.sh"), "x86", "G_ADD", out],
                capture_output=True, text=True, env=self.clean_env())
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("AB_TREE", done.stderr)
        self.assertIn("export AB_TREE=", done.stderr)

    def test_run_u_end_to_end_without_roots(self):
        with tempfile.TemporaryDirectory() as out:
            done = subprocess.run(
                ["bash", str(ROOT / "run-u-end-to-end.sh"), "x86",
                 "/nonexistent/queries.jsonl", out],
                capture_output=True, text=True, env=self.clean_env())
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("AB_BUILD", done.stderr)


class Sibling(unittest.TestCase):
    def test_new_name_wins_when_both_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "gisel-anchor").mkdir()
            (root / "upstream-source").mkdir()
            self.assertEqual(
                paths.sibling(root, "NO_SUCH_ENV_FOR_TEST",
                              "gisel-anchor", "upstream-source"),
                root / "gisel-anchor")

    def test_old_name_is_the_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "upstream-source").mkdir()
            self.assertEqual(
                paths.sibling(root, "NO_SUCH_ENV_FOR_TEST",
                              "gisel-anchor", "upstream-source"),
                root / "upstream-source")

    def test_env_override_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "gisel-anchor").mkdir()
            with mock.patch.dict(os.environ, {"UPSTREAM_SOURCE": "/somewhere"}):
                self.assertEqual(
                    paths.sibling(root, "UPSTREAM_SOURCE",
                                  "gisel-anchor", "upstream-source"),
                    Path("/somewhere"))


if __name__ == "__main__":
    unittest.main()
