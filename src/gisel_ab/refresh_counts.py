#!/usr/bin/env python3
"""Recompute `query_count` in targets/*.json from the current gisel corpus.

    ./refresh-counts.py [--check] [TARGET...]

`gisel cases` is the generator and `query_count` is its output, so the number
rotates whenever the corpus or the generator does.  A stale count makes
`ab.py run` reject a freshly generated query file (validate_queries), which is
how we noticed.  Refresh it here instead of in each manifest by hand.

--check compares and exits 1 without writing (CI); the default rewrites the
manifest.  AArch64 needs its axes file and takes about five minutes; pass
target names to limit the run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PKG = Path(__file__).resolve().parent
GISEL = Path(os.environ.get("GISEL_SRC", PKG.parents[1].parent / "gisel")).resolve()
TARGETS = PKG / "data" / "targets"


def count(spec: dict) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "queries.jsonl"
        cmd = [sys.executable, "-m", "gisel", "cases",
               str(GISEL / spec["source"]),
               "--features", str(GISEL / spec["features"]),
               "--out", str(out), "--json"]
        if spec.get("axes"):
            cmd += ["--axes", str(GISEL / spec["axes"])]
        proc = subprocess.run(cmd, cwd=GISEL, capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit("%s: gisel cases failed: %s"
                             % (spec["name"], proc.stderr.strip()[-400:]))
        return json.loads(proc.stdout)["cases"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="report drift and exit 1 instead of rewriting")
    ap.add_argument("targets", nargs="*", help="limit to these adapters")
    args = ap.parse_args()

    paths = [p for p in sorted(TARGETS.glob("*.json"))
             if not args.targets or p.stem in args.targets]
    specs = []
    for path in paths:
        spec = json.loads(path.read_text())
        if spec.get("query_count") is None:
            continue
        specs.append((path, spec))

    stale = 0
    with ThreadPoolExecutor(max_workers=min(8, len(specs) or 1)) as pool:
        got = list(pool.map(lambda ps: count(ps[1]), specs))
    for (path, spec), value in zip(specs, got):
        old = spec["query_count"]
        mark = "ok" if old == value else "DRIFT"
        print("%-9s %6d -> %6d  %s" % (spec["name"], old, value, mark))
        if old != value:
            stale += 1
            spec["query_count"] = value
            if not args.check:
                path.write_text(json.dumps(spec, indent=2) + "\n")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
