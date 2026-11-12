#!/usr/bin/env python3
"""L3: run the whole check-llvm twice and compare it test by test.

    ./l3.py run --out /tmp/l3-final
    ./l3.py compare /tmp/l3-final --json /tmp/l3-final/l3-summary.json

`run` does what docs/REPORT-mir.md section 6 describes, one command:

  1. baseline round on the restored tree: lit over the build's test dir;
  2. point the three legalizer constructors at gisel's .inc, rebuild;
  3. combined round: the same lit;
  4. restore the three constructors, rebuild, and record the library hashes.

Per-test evidence uses lit's `--resultdb-output`, not `--xunit-xml-output`:
xunit prints XFAIL as a plain passing <testcase>, so a PASS<->XFAIL swap would
be invisible there.  ResultDB carries (status, expected) per test, which is
the result code in disguise: PASS=(PASS,True), XFAIL=(FAIL,True),
FAIL=(FAIL,False), XPASS=(PASS,False), UNSUPPORTED=(SKIP,True).

`compare` fails on a test that exists on only one side or whose (status,
expected) changed.  Two green summaries are not enough on their own: a
PASS->XFAIL flip and an XFAIL->PASS flip cancel out in the totals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TREE = Path("/home/ubuntu/llvm/trees/explore")
DEFAULT_BUILD = Path("/home/ubuntu/llvm/builds/explore")
GISEL = Path(os.environ.get("GISEL_SRC", HERE.parent / "gisel")).resolve()
SWAP = HERE / "swap-source-ctor.py"
LIB = "libLLVM%sCodeGen.so.24.0git"
NAMES = {"x86": "X86", "aarch64": "AArch64", "riscv": "RISCV"}
TARGETS = ("x86", "aarch64", "riscv")


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def lib(build: Path, target: str) -> Path:
    return build / "lib" / (LIB % NAMES[target])


def announce(cmd: list[str]) -> None:
    print("$", " ".join(cmd), flush=True)


def call(cmd: list[str], log: Path | None = None, **kw) -> int:
    announce(cmd)
    if log is None:
        return subprocess.run(cmd, check=False, **kw).returncode
    with log.open("wb") as handle:
        proc = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT, **kw)
    return proc.returncode


def git(tree: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(tree), *args],
                          capture_output=True, text=True,
                          check=True).stdout.strip()


def lit(build: Path, out: Path, tag: str) -> dict:
    """One lit round.  Returns rc, elapsed, and the two report paths."""
    resultdb = out / ("%s.resultdb.json" % tag)
    xunit = out / ("%s.xunit.xml" % tag)
    started = time.time()
    rc = call([str(build / "bin" / "llvm-lit"), "-sv",
               "--resultdb-output=%s" % resultdb,
               "--xunit-xml-output=%s" % xunit,
               str(build / "test")],
              log=out / ("%s.lit.log" % tag), cwd=build / "test")
    return {"rc": rc, "elapsed_seconds": round(time.time() - started, 1),
            "resultdb": resultdb.name, "xunit": xunit.name}


def run(args) -> int:
    tree, build, out = args.tree, args.build, args.out
    out.mkdir(parents=True, exist_ok=True)

    head = git(tree, "rev-parse", "HEAD")
    dirty = git(tree, "status", "--porcelain")
    if dirty:
        raise SystemExit("tree %s is not clean:\n%s" % (tree, dirty))

    incs = {}
    for target in TARGETS:
        inc = GISEL / "tests" / "artifacts" / ("%s.inc" % target)
        if not inc.exists():
            raise SystemExit("missing %s (run gisel gen first)" % inc)
        incs[target] = {"path": str(inc), "sha256": sha256(inc)}

    provenance = {
        "tree": str(tree), "tree_head": head, "build": str(build),
        "jobs": args.jobs, "incs": incs,
        "libs": {"baseline": {}, "swapped": {}, "restored": {}},
        "rounds": {},
    }

    print("== baseline")
    provenance["libs"]["baseline"] = {t: sha256(lib(build, t)) for t in TARGETS}
    provenance["rounds"]["baseline"] = lit(build, out, "baseline")
    if provenance["rounds"]["baseline"]["rc"] != 0:
        raise SystemExit("baseline lit failed, stop before swapping")

    print("== combined")
    try:
        for target in TARGETS:
            cmd = [sys.executable, str(SWAP), "apply", "--target", target,
                   "--tree", str(tree), "--inc", incs[target]["path"]]
            if call(cmd) != 0:
                raise SystemExit("%s: swap failed" % target)
        if call(["ninja", "-C", str(build), "-j", str(args.jobs)]) != 0:
            raise SystemExit("build failed after swap")
        provenance["libs"]["swapped"] = {t: sha256(lib(build, t))
                                         for t in TARGETS}
        provenance["rounds"]["combined"] = lit(build, out, "combined")
    finally:
        # A failed swap or build must not leave a patched constructor behind,
        # even when the tree is already patched for only some of the targets.
        print("== restore")
        for target in TARGETS:
            call([sys.executable, str(SWAP), "restore", "--target", target,
                  "--tree", str(tree)])
        call(["ninja", "-C", str(build), "-j", str(args.jobs)])
        provenance["libs"]["restored"] = {t: sha256(lib(build, t))
                                          for t in TARGETS}
        provenance["tree_clean_after"] = not git(tree, "status", "--porcelain")
        provenance["libs"]["restored_exactly"] = {
            t: provenance["libs"]["restored"][t]
            == provenance["libs"]["baseline"][t] for t in TARGETS}

    (out / "l3-provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(json.dumps(provenance, indent=2, sort_keys=True))
    return 0 if provenance["tree_clean_after"] else 1


def counts(tests: dict) -> dict:
    got = {"tests": len(tests), "passed": 0, "xfail": 0, "failed": 0,
           "xpass": 0, "unsupported": 0, "aborted": 0}
    for status, expected in tests.values():
        if status == "PASS":
            got["passed" if expected else "xpass"] += 1
        elif status == "FAIL":
            got["xfail" if expected else "failed"] += 1
        elif status == "SKIP":
            got["unsupported"] += 1
        else:
            got["aborted"] += 1
    return got


def load(path: Path) -> dict[str, tuple[str, bool]]:
    data = json.loads(path.read_text())
    return {t["testId"]: (t.get("status"), bool(t.get("expected")))
            for t in data["tests"]}


def write_tests(path: Path, tests: dict[str, tuple[str, bool]]) -> None:
    """The compact, deterministic per-test record that gets frozen.

    ResultDB is 154 MB per round because every test carries its output; the
    (status, expected) pair is the part the comparison needs.
    """
    with path.open("w") as handle:
        for name in sorted(tests):
            status, expected = tests[name]
            handle.write(json.dumps({"test": name, "status": status,
                                     "expected": expected},
                                    sort_keys=True) + "\n")


def read_tests(path: Path) -> dict[str, tuple[str, bool]]:
    got = {}
    for line in path.read_text().splitlines():
        row = json.loads(line)
        got[row["test"]] = (row["status"], row["expected"])
    return got


def log_counts(path: Path) -> dict:
    """The five numbers lit prints, including the ones ResultDB drops."""
    import re
    keys = {"Total Discovered Tests": "discovered", "Skipped": "skipped",
            "Unsupported": "unsupported", "Passed": "passed",
            "Expectedly Failed": "xfail", "Failed": "failed",
            "Unexpectedly Passed": "xpass", "Timeout": "timeout",
            "Unresolved": "unresolved"}
    got = {}
    text = path.read_text(errors="replace")
    for match in re.finditer(r"^\s*(%s)\s*:\s*(\d+)"
                             % "|".join(keys), text, re.M):
        got[keys[match.group(1)]] = int(match.group(2))
    return got


def compare(args) -> int:
    out = args.dir
    summary = {}
    tests = {}
    for side in ("baseline", "combined"):
        resultdb = out / ("%s.resultdb.json" % side)
        tests[side] = load(resultdb)
        write_tests(out / ("l3-%s.tests.jsonl" % side), tests[side])
        summary[side] = counts(tests[side])
        summary["log.%s" % side] = log_counts(out / ("%s.lit.log" % side))

    base, swap = tests["baseline"], tests["combined"]
    extra = sorted(set(base) - set(swap))
    missing = sorted(set(swap) - set(base))
    changed = sorted(name for name in set(base) & set(swap)
                     if base[name] != swap[name])
    summary.update({
        "tests_compared": len(set(base) & set(swap)),
        "only_in_baseline": extra,
        "only_in_combined": missing,
        "changed": [{"test": name, "baseline": list(base[name]),
                     "combined": list(swap[name])} for name in changed],
        "resultdb_sha256": {
            side: sha256(out / ("%s.resultdb.json" % side))
            for side in ("baseline", "combined")},
        "tests_file_sha256": {
            side: sha256(out / ("l3-%s.tests.jsonl" % side))
            for side in ("baseline", "combined")},
        "identical": not (extra or missing or changed),
    })
    text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.json:
        args.json.write_text(text)
    print(text)
    return 0 if summary["identical"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    go = sub.add_parser("run", help="baseline + combined + restore")
    go.add_argument("--out", type=Path, required=True)
    go.add_argument("--tree", type=Path, default=DEFAULT_TREE)
    go.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    go.add_argument("--jobs", type=int, default=min(32, os.cpu_count() or 4))
    go.set_defaults(func=run)
    cmp_ = sub.add_parser("compare", help="compare the two rounds")
    cmp_.add_argument("dir", type=Path)
    cmp_.add_argument("--json", type=Path)
    cmp_.set_defaults(func=compare)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
