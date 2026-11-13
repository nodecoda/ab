"""`gisel-ab doctor`: can this workbench run a comparison right now?

The harness has four external preconditions -- an LLVM checkout at the pin, a
ninja build of it, gisel, and a writable state directory -- and when one is
missing the failure lands deep inside a run that has already built a runner.
This command checks them up front and prints the `export` line or the
`ninja` command that fixes each one.

It is read-only: nothing is compiled, no files are swapped, no lock is taken
for longer than the check itself.  Exit codes follow the harness convention:
0 every check passed (warnings allowed), 2 something failed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import paths

AB_ROOT = Path(__file__).resolve().parent
OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""

    def as_dict(self) -> dict:
        out = {"name": self.name, "status": self.status, "detail": self.detail}
        if self.fix:
            out["fix"] = self.fix
        return out


def _git(path: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(path), *args],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _pin_path() -> Path:
    explicit = os.environ.get("GS_PIN")
    if explicit:
        return Path(explicit).expanduser()
    return (paths.sibling(AB_ROOT.parent, "UPSTREAM_SOURCE",
                          "gisel-anchor", "upstream-source")
            / "pin" / "PIN.json")


def _python() -> Check:
    version = ".".join(str(n) for n in sys.version_info[:3])
    if sys.version_info < (3, 10):
        return Check("python", FAIL, version,
                     "the harness needs Python 3.10 or newer")
    return Check("python", OK, version)


def _gisel() -> Check:
    try:
        import gisel
    except ImportError:
        # ab.py puts GISEL_SRC (default: the sibling checkout) on sys.path so
        # the harness works without installing gisel; doctor must judge the
        # same installation the harness will use.
        candidate = Path(os.environ.get("GISEL_SRC",
                                        AB_ROOT.parent / "gisel")).resolve()
        if candidate.is_dir():
            sys.path.insert(0, str(candidate))
        try:
            import gisel
        except ImportError as exc:
            return Check("gisel", FAIL, str(exc),
                         "pip install gisel, or export GISEL_SRC=<checkout>")
    path = Path(gisel.__file__).resolve().parent
    return Check("gisel", OK, "%s at %s" % (gisel.__version__, path))


def _pin() -> Check:
    path = _pin_path()
    try:
        doc = json.loads(path.read_text())
    except FileNotFoundError:
        return Check("pin", FAIL, "missing: %s" % path,
                     "clone gisel-anchor next to gisel-ab, or export "
                     "GS_PIN=<gisel-anchor>/pin/PIN.json")
    except json.JSONDecodeError as exc:
        return Check("pin", FAIL, "bad JSON in %s: %s" % (path, exc),
                     "restore pin/PIN.json from gisel-anchor")
    commit = str(doc.get("commit", ""))
    if len(commit) != 40:
        return Check("pin", FAIL, "no 40-hex commit in %s" % path,
                     "restore pin/PIN.json from gisel-anchor")
    return Check("pin", OK, "%s commit %s" % (path.name, commit[:12]))


def _tree(tree: Path | None, pin_commit: str | None) -> Check:
    if tree is None:
        return Check("tree", FAIL, "AB_TREE is not set",
                     "export AB_TREE=/path/to/llvm-project (a pin-compatible "
                     "checkout); --tree overrides it")
    if not (tree / "llvm").is_dir():
        return Check("tree", FAIL, "%s has no llvm/ directory" % tree,
                     "point AB_TREE at the llvm-project checkout root")
    head = _git(tree, "rev-parse", "HEAD")
    if head is None:
        return Check("tree", FAIL, "%s is not a git checkout" % tree,
                     "the pin check reads the commit; clone llvm-project")
    detail = "HEAD %s" % head[:12]

    # Ancestry is not the check: PIN.json freezes the *content* of twelve
    # files, because a main that contains the pin commit can still carry a
    # different legalizer.  check-pin.sh is the authority; doctor only relays
    # its verdict so the harness cannot start on a tree it will reject later.
    script = AB_ROOT / "check-pin.sh"
    if not script.is_file():
        return Check("tree", FAIL, "check-pin.sh is missing from %s" % AB_ROOT,
                     "this is not a complete ab checkout")
    try:
        done = subprocess.run(["bash", str(script), str(tree)],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("tree", FAIL, "cannot run check-pin.sh: %s" % exc,
                     "install bash and git")
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    if done.returncode != 0:
        first = lines[0] if lines else "content check failed"
        return Check("tree", FAIL, "%s; %s" % (detail, first),
                     "point AB_TREE at the frozen official tree (the one "
                     "PIN.json `official_base` describes), not at main")
    detail += " (content matches official_base)"
    dirty = _git(tree, "status", "--porcelain")
    if dirty:
        n = len(dirty.splitlines())
        return Check("tree", WARN, "%s, %d modified file(s)" % (detail, n),
                     "a dirty tree can mean a stale swap; `ab verify` says "
                     "whether the build is back on baseline")
    return Check("tree", OK, detail)


def _build(build: Path | None) -> Check:
    if build is None:
        return Check("build", FAIL, "AB_BUILD is not set",
                     "export AB_BUILD=/path/to/build (its ninja build); "
                     "--build overrides it")
    if not (build / "build.ninja").is_file():
        return Check("build", FAIL, "%s has no build.ninja" % build,
                     "point AB_BUILD at a configured ninja build directory")
    llc = build / "bin" / "llc"
    if not llc.is_file():
        return Check("build", FAIL, "no bin/llc in %s" % build,
                     "run `ninja -C %s llc`" % build)
    return Check("build", OK, "%s (llc present)" % build)


def _ninja() -> Check:
    found = shutil.which(os.environ.get("NINJA", "ninja"))
    if not found:
        return Check("ninja", FAIL, "not on PATH",
                     "install ninja, or export NINJA=/path/to/ninja")
    return Check("ninja", OK, found)


def _disk(build: Path | None) -> Check:
    probe = build if build and build.is_dir() else AB_ROOT
    try:
        free = shutil.disk_usage(probe).free
    except OSError as exc:
        return Check("disk", WARN, "cannot measure %s: %s" % (probe, exc))
    gb = free / (1 << 30)
    detail = "%.1f GB free at %s" % (gb, probe)
    if gb < 20:
        return Check("disk", WARN, detail,
                     "a full LLVM build plus two runners needs ~20 GB; "
                     "clean stale state under ab/.ab")
    return Check("disk", OK, detail)


def _state() -> Check:
    root = AB_ROOT / ".ab"
    if not root.is_dir():
        return Check("state", OK, "no state yet (first run will create it)")
    ledgers = sorted(root.glob("*/ledger.jsonl"))
    if not ledgers:
        return Check("state", OK, "%d state dir(s), no completed run"
                     % len([p for p in root.iterdir() if p.is_dir()]))
    last = ledgers[-1]
    line = last.read_text().strip().splitlines()[-1]
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return Check("state", WARN, "%s has an unparsable last line" % last)
    keys = ", ".join(sorted(record)[:4])
    return Check("state", OK, "last run %s: %s" % (last.parent.name, keys))


def _locks() -> Check:
    root = AB_ROOT / ".ab"
    held = []
    for lock in root.glob("*/lock") if root.is_dir() else []:
        try:
            import fcntl
            with open(lock, "a+") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError:
            held.append(lock.parent.name)
        except ImportError:
            break
    if held:
        return Check("locks", WARN, "held by: %s" % " ".join(sorted(held)),
                     "a run is in progress; if it crashed, wait for the "
                     "process to disappear rather than deleting the lock")
    return Check("locks", OK, "no lock is held")


def _targets() -> Check:
    found = sorted(p.name for p in (AB_ROOT / "targets").glob("*.json")
                   if p.name != "schema.json")
    if not found:
        return Check("targets", FAIL, "no targets/*.json",
                     "this is not an ab checkout; clone it again")
    return Check("targets", OK, "%d: %s" % (len(found),
                                            " ".join(p[:-5] for p in found)))


def checks(tree: Path | None = None, build: Path | None = None) -> list[Check]:
    pin = _pin()
    pin_commit = None
    if pin.status == OK:
        pin_commit = json.loads(_pin_path().read_text())["commit"]
    return [_python(), _gisel(), pin, _tree(tree, pin_commit),
            _build(build), _ninja(), _disk(build), _state(), _locks(),
            _targets()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gisel-ab doctor",
        description="check the LLVM tree, build, gisel and state a comparison "
                    "needs; read-only")
    ap.add_argument("--tree", help="LLVM checkout (default: AB_TREE)")
    ap.add_argument("--build", help="ninja build (default: AB_BUILD)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    tree = Path(args.tree).resolve() if args.tree else (
        Path(os.environ["AB_TREE"]).expanduser().resolve()
        if os.environ.get("AB_TREE") else None)
    build = Path(args.build).resolve() if args.build else (
        Path(os.environ["AB_BUILD"]).expanduser().resolve()
        if os.environ.get("AB_BUILD") else None)

    found = checks(tree, build)
    failed = [c for c in found if c.status == FAIL]
    if args.json:
        print(json.dumps({"ok": not failed,
                          "checks": [c.as_dict() for c in found]},
                         indent=1, sort_keys=True))
    else:
        print("gisel-ab doctor")
        for check in found:
            print("%-10s %-4s %s" % (check.name, check.status, check.detail))
            if check.fix:
                print("%-10s      fix: %s" % ("", check.fix))
        print("%d/%d ok, %d failed"
              % (len(found) - len(failed), len(found), len(failed)))
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
