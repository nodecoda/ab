#!/usr/bin/env python3
"""MIR-layer plumbing: snapshot CodeGen libraries, swap, and run ``llc``.

The MIR layer never rebuilds the whole tree.  It

1. snapshots the official ``libLLVM<T>CodeGen.so``,
2. points the target's legalizer constructor at the generated ``.inc``
   through ``swap-source-ctor.py`` and rebuilds only that shared library,
3. snapshots the replaced library,
4. restores the source and rebuilds the baseline library.

Replay then runs one ``bin/llc`` twice, selecting the library with
``LD_LIBRARY_PATH`` (``llc`` uses ``DT_RUNPATH``, so the environment wins).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SWAP = ROOT / "swap-source-ctor.py"
INJECT = ROOT / "inject-missing-opcode.py"
NINJA = os.environ.get("NINJA", "ninja")
DEFAULT_GISEL = Path(os.environ.get("GISEL_SRC", ROOT.parent / "gisel")).resolve()

# LLVM test directory names differ from the adapter names.
TEST_DIR = {
    "x86": "X86",
    "aarch64": "AArch64",
    "riscv": "RISCV",
    "arm": "ARM",
    "mips": "Mips",
    "wasm": "WebAssembly",
    "ppc": "PowerPC",
    "m68k": "M68k",
    "spirv": "SPIRV",
}

# Targets whose constructor body can be replaced in the source tree today.
SWAPPABLE = ("x86", "aarch64", "riscv", "arm", "ppc", "mips",
             "m68k", "wasm")


class MirError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_target(name: str) -> dict:
    path = ROOT / "targets" / (name + ".json")
    if not path.exists():
        raise MirError("unknown target %r (no %s)" % (name, path))
    return json.loads(path.read_text())


def codegen_lib(build: Path, spec: dict) -> Path:
    return build / spec["library"]


def ninja_target(spec: dict) -> str:
    if spec.get("ninja_target"):
        return spec["ninja_target"]
    name = Path(spec["library"]).name
    match = re.match(r"(libLLVM.+CodeGen)\.so", name)
    if not match:
        raise MirError("cannot derive a ninja target from %s" % name)
    return match.group(1) + ".so"


def run(cmd, cwd=None, env=None) -> subprocess.CompletedProcess:
    proc = subprocess.run([str(part) for part in cmd], cwd=str(cwd) if cwd else None,
                          env=env, capture_output=True, text=True)
    if proc.returncode:
        raise MirError("command failed (%d): %s\n%s"
                       % (proc.returncode, " ".join(str(part) for part in cmd),
                          (proc.stderr or proc.stdout).strip()))
    return proc


def ninja(build: Path, spec: dict):
    run([NINJA, "-C", build, ninja_target(spec)])


def git_head(tree: Path) -> str:
    return run(["git", "-C", tree, "rev-parse", "HEAD"]).stdout.strip()


def git_dirty_paths(tree: Path, paths) -> list[str]:
    proc = run(["git", "-C", tree, "status", "--porcelain", "--", *paths])
    return [line for line in proc.stdout.splitlines() if line.strip()]


def generate_inc(gisel: Path, spec: dict, out: Path) -> Path:
    dest = out / spec["inc_name"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(gisel) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    run([sys.executable, "-m", "gisel", "gen", gisel / spec["source"],
         "--emit=inc", "--out", dest], cwd=gisel, env=env)
    if not dest.exists():
        raise MirError("gisel gen did not write %s" % dest)
    return dest


def mutate_inc(inc: Path, opcode: str, out: Path) -> Path:
    dest = out / ("mutant-" + inc.name)
    run([sys.executable, INJECT, inc, opcode, dest])
    return dest


def swap_apply(target: str, tree: Path, inc: Path):
    if target not in SWAPPABLE:
        raise MirError("target %r has no constructor swap yet" % target)
    run([sys.executable, SWAP, "apply", "--target", target,
         "--tree", tree, "--inc", inc])


def swap_restore(target: str, tree: Path):
    if target not in SWAPPABLE:
        raise MirError("target %r has no constructor swap yet" % target)
    run([sys.executable, SWAP, "restore", "--target", target, "--tree", tree])


def snapshot_lib(spec: dict, build: Path, dest: Path) -> tuple[Path, str]:
    src = codegen_lib(build, spec)
    if not src.exists():
        raise MirError("library not found: %s" % src)
    dest.mkdir(parents=True, exist_ok=True)
    dst = dest / src.name
    shutil.copyfile(src, dst)
    return dst, sha256(dst)


def prepare_target(target: str, tree: Path, build: Path, out: Path,
                   gisel: Path = DEFAULT_GISEL,
                   mutate_opcode: str | None = None) -> dict:
    """Snapshot official, build ours, snapshot ours, restore baseline.

    The source file is byte-compared before and after, and the restore runs in
    ``finally`` so an interrupted build cannot leave the tree patched.
    """
    spec = load_target(target)
    source = tree / spec["touch_source"]
    if not source.exists():
        raise MirError("source not found: %s" % source)
    dirty = git_dirty_paths(tree, [spec["touch_source"]])
    if dirty:
        raise MirError("tree is already dirty at %s; restore it first"
                       % spec["touch_source"])
    source_sha = sha256(source)

    official_dir = out / "official" / target
    official_lib, official_sha = snapshot_lib(spec, build, official_dir)

    inc = generate_inc(gisel, spec, out / "inc")
    inc_sha = sha256(inc)
    if mutate_opcode:
        inc = mutate_inc(inc, mutate_opcode, out / "inc")
        inc_sha = sha256(inc)

    side = "ours-negative" if mutate_opcode else "ours"
    ours_lib = None
    ours_sha = None
    try:
        swap_apply(target, tree, inc)
        ninja(build, spec)
        ours_lib, ours_sha = snapshot_lib(spec, build, out / side / target)
    finally:
        swap_restore(target, tree)
        ninja(build, spec)

    source_after = sha256(source)
    if source_after != source_sha:
        raise MirError("restore did not reproduce %s (%s -> %s)"
                       % (source, source_sha[:12], source_after[:12]))
    lib_after = sha256(codegen_lib(build, spec))

    return {
        "adapter": spec["name"],
        # The target file may describe the L0 runner strategy;  the MIR layer
        # records the constructor swap it actually used.
        "strategy": spec.get("mir_strategy", spec["strategy"]),
        "inc": str(inc),
        "inc_sha256": inc_sha,
        "mutate_opcode": mutate_opcode,
        "official_lib": str(official_lib),
        "official_lib_sha256": official_sha,
        "ours_lib": str(ours_lib),
        "ours_lib_sha256": ours_sha,
        "source": str(source),
        "source_sha256": source_sha,
        "baseline_lib_after_restore_sha256": lib_after,
        "baseline_lib_restored_exactly": lib_after == official_sha,
    }


class Lock:
    """One writer per output directory; flock is released on process exit."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "w")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.handle.close()
            raise MirError("another run holds %s" % self.path)
        self.handle.write(str(os.getpid()))
        self.handle.flush()
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()
        return False


def run_llc(llc: Path, lib_dir: Path, args, timeout: float = 60.0,
            cwd: Path | None = None) -> dict:
    env = dict(os.environ)
    prefix = str(lib_dir)
    if env.get("LD_LIBRARY_PATH"):
        prefix += os.pathsep + env["LD_LIBRARY_PATH"]
    env["LD_LIBRARY_PATH"] = prefix
    try:
        proc = subprocess.run([str(llc), *[str(a) for a in args]],
                              cwd=str(cwd) if cwd else None, env=env,
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        def text(value):
            if value is None:
                return ""
            return value.decode(errors="replace") if isinstance(value, bytes) else value
        return {"rc": None, "timeout": True,
                "out": text(exc.stdout), "err": text(exc.stderr)}
    return {"rc": proc.returncode, "timeout": False,
            "out": proc.stdout, "err": proc.stderr}
