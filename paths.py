"""Where the LLVM checkout and build live.

There is deliberately no default.  A default that points at the machine the
harness was written on either fails with a confusing FileNotFoundError deep in
a run or, worse, swaps files inside someone else's checkout.  Every entry
point takes ``--tree``/``--build`` or reads ``AB_TREE``/``AB_BUILD``; the
cohort driver also accepts ``COHORT_TREE`` and ``COHORT_LLVM``.

Failures print one actionable line and exit 2, the same code the shell scripts
and ``ab.py`` use for input errors.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

TREE_ENVS = ("AB_TREE", "COHORT_TREE")
BUILD_ENVS = ("AB_BUILD",)
LLVM_ENVS = ("COHORT_LLVM", "AB_LLVM_REPO")


def _from_env(envs):
    for name in envs:
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser()
    return None


def _fail(label, envs, example, hint):
    print("input error: %s is not set" % label, file=sys.stderr)
    print("  export %s=%s" % (envs[0], example), file=sys.stderr)
    if len(envs) > 1:
        print("  (also accepted: %s)" % ", ".join(envs[1:]), file=sys.stderr)
    if hint:
        print("  " + hint, file=sys.stderr)
    raise SystemExit(2)


def _bad_shape(label, path, detail):
    print("input error: %s does not look like %s: %s"
          % (label, detail, path), file=sys.stderr)
    raise SystemExit(2)


def require_tree(explicit=None) -> Path:
    """The llvm-project checkout (``llvm/`` and ``.git`` live here)."""
    path = Path(explicit).expanduser() if explicit else _from_env(TREE_ENVS)
    if path is None:
        _fail("AB_TREE (LLVM source checkout)", TREE_ENVS,
              "/path/to/llvm-project", "or pass --tree DIR")
    path = path.resolve()
    if not (path / "llvm" / "include" / "llvm").is_dir():
        _bad_shape("AB_TREE", path, "an llvm-project checkout")
    return path


def require_build(explicit=None) -> Path:
    """The LLVM build directory (``build.ninja`` or ``CMakeCache.txt``)."""
    path = Path(explicit).expanduser() if explicit else _from_env(BUILD_ENVS)
    if path is None:
        _fail("AB_BUILD (LLVM build directory)", BUILD_ENVS,
              "/path/to/build", "or pass --build DIR")
    path = path.resolve()
    if not ((path / "build.ninja").is_file()
            or (path / "CMakeCache.txt").is_file()):
        _bad_shape("AB_BUILD", path, "an LLVM build directory")
    return path


def llvm_repo(explicit=None, fallback=None) -> Path:
    """A git checkout that can ``git show <pin>:<path>``.

    ``COHORT_LLVM``/``AB_LLVM_REPO`` win; a pinned source tree is the last
    resort because ``git show`` only works if that worktree shares the objects.
    """
    path = Path(explicit).expanduser() if explicit else _from_env(LLVM_ENVS)
    if path is None and fallback is not None:
        path = Path(fallback).expanduser()
    if path is None:
        _fail("COHORT_LLVM (llvm-project git repository)", LLVM_ENVS,
              "/path/to/llvm-project",
              "or set COHORT_TREE/AB_TREE to a checkout that has the pin")
    path = path.resolve()
    if not (path / ".git").exists():
        _bad_shape("COHORT_LLVM", path, "a git checkout")
    return path
