#!/usr/bin/env python3
"""Replay a freshly generated include against the frozen official answers.

    replay-frozen.py TARGET --tree TREE --build BUILD --out OUT \\
        [--direction G|U|both]

`verify-evidence.sh` proves the frozen artifacts did not change.  This script
answers the other question: after a `.gisel` edit, does the new `inc` still
give the same answers to the questions that were frozen?  It never re-answers
the official side; the frozen `official.answers.jsonl` is the reference.

G is the corpus-derived query set; U is the upstream-derived set.  Both were
freezed per target under `oracle/<direction>/<target>/`.
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import ab  # noqa: E402

SCALARS = (
    "agree", "answered_equal", "disagree", "errors", "matched",
    "missing_ours", "missing_ref", "ours", "ref", "ref_asserted",
    "unanswerable",
)


def frozen_bytes(directory: Path, name: str) -> bytes:
    path = directory / name
    if not path.exists():
        path = directory / (name + ".gz")
    if not path.exists():
        raise SystemExit("missing frozen artifact: %s" % path)
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def materialize(direction: str, target: str, out: Path):
    directory = ROOT / "oracle" / direction / target
    work = out / direction
    work.mkdir(parents=True, exist_ok=True)
    queries = work / "queries.jsonl"
    official = work / "official.answers.jsonl"
    queries.write_bytes(frozen_bytes(directory, "queries.jsonl"))
    official.write_bytes(frozen_bytes(directory, "official.answers.jsonl"))
    expected = json.loads(frozen_bytes(directory, "diff.json"))
    return work, queries, official, expected


def build_ours(target: dict, tree: Path, build: Path, inc: Path, out: Path) -> Path:
    if target["strategy"] == "swap-source":
        try:
            ab.swap_source("restore", target, tree)
            ab.ninja(build, target["ninja_target"])
            # The replaced library is built from a patched tree, so the pin
            # check has to run here, on the restored text, and the ours build
            # skips it.
            ab.run_checked([ROOT / "check-pin.sh", tree])
            ab.swap_source("apply", target, tree, inc)
            ab.ninja(build, target["ninja_target"])
            return ab.build_swap_runner(target, tree, build, out,
                                        "runner.ours", skip_pin=True)
        finally:
            ab.swap_source("restore", target, tree)
            ab.ninja(build, target["ninja_target"])
    if target["strategy"] == "generated-ctor":
        _, ours = ab.build_ctor_runners(target, tree, build, inc, out)
        return ours
    raise SystemExit("unknown strategy %r" % target["strategy"])


def diff_command(expected: dict, official: Path, ours: Path,
                 queries: Path) -> list[str]:
    """Replay the classification the frozen entry used.

    Both flags pin an exact count, so this cannot hide a new class of
    difference: a different number of reference assertions fails the run.
    """
    cmd = [sys.executable, str(ROOT / "diff.py"), str(official), str(ours),
           "--json", "--queries", str(queries)]
    if expected.get("ref_asserted"):
        cmd += ["--allow-ref-asserts", str(expected["ref_asserted"])]
    if expected.get("unanswerable"):
        cmd += ["--expect-unanswerable", str(expected["unanswerable"])]
    return cmd


def compare(frozen: dict, fresh: dict) -> list[str]:
    bad = []
    for key in SCALARS:
        if key in frozen and fresh.get(key) != frozen[key]:
            bad.append("%s=%r, frozen %r" % (key, fresh.get(key), frozen[key]))
    return bad


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="replay-frozen")
    parser.add_argument("target")
    parser.add_argument("--tree", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--direction", choices=("G", "U", "both"), default="G")
    parser.add_argument("--gisel", default=str(ab.GISEL))
    args = parser.parse_args(argv)

    target = ab.load_target(args.target)
    tree = Path(args.tree).resolve()
    build = Path(args.build).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    directions = ("G", "U") if args.direction == "both" else (args.direction,)

    plans = {d: materialize(d, args.target, out) for d in directions}
    source = Path(args.gisel).resolve() / target["source"]
    inc = ab.generate_inc(target, source, out)
    print("inc=%s sha256=%s" % (inc, ab.sha256(inc)[:16]))

    runner = build_ours(target, tree, build, inc, out)
    print("runner=%s" % runner)

    failed = 0
    for direction in directions:
        work, queries, official, expected = plans[direction]
        ours = work / "ours.answers.jsonl"
        ab.answer(runner, queries, ours)
        proc = subprocess.run(
            diff_command(expected, official, ours, queries), capture_output=True,
            text=True)
        if proc.returncode:
            print("%s: diff failed: %s" % (direction, proc.stderr.strip()))
            failed += 1
            continue
        fresh = json.loads(proc.stdout)
        bad = compare(expected, fresh)
        if bad:
            failed += 1
            print("%s: MISMATCH: %s" % (direction, "; ".join(bad)))
        else:
            print("%s: matches frozen (%d agreed, %d disagree, %d ours)"
                  % (direction, fresh.get("agree", -1),
                     fresh.get("disagree", -1), fresh.get("ours", -1)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
