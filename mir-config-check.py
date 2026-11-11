#!/usr/bin/env python3
"""Check that every gisel config has a realizable llc spelling.

    mir-config-check.py --target x86 --features F.json [--llc LLC] [--json]
                        [--mutate CONFIG]

What this proves
----------------
1. every config name in the gisel feature truth table appears in
   ``data/mir-configs.json`` -- either with a ``mattr`` list (realizable) or
   deliberately without one (``config_unrealizable``, with a ``source`` that
   says why);
2. ``llc`` accepts the triple plus ``-mattr``/``args`` of every realizable
   config on a trivial module (rc 0), and every feature name is a real
   subtarget feature of that triple (``-mattr=help``);
3. ``--mutate`` replaces one config's feature list with a name no target
   knows, and the check must then fail (rc 0 for the control) -- without
   that, "all configs accepted" could just mean the checker never looks.

What this does not prove
------------------------
That ``-mattr`` produces the same boolean values as the truth table.  That is
proved behaviourally by L2: queries generated under a config are replayed
under the same config, so a wrong mapping shows up as an answer mismatch.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIGS = ROOT / "data" / "mir-configs.json"


def load_features(path: Path):
    return list(json.loads(path.read_text()))


def accepted_features(llc: Path, triple: str):
    # `-mattr=help` prints the feature list on stderr.
    proc = subprocess.run([str(llc), "-mtriple=" + triple, "-mattr=help"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return None, proc.stderr.strip()
    names = set()
    for line in (proc.stdout + proc.stderr).splitlines():
        match = re.match(r"^\s{2}([A-Za-z0-9][A-Za-z0-9_.-]*)\s{2,}-", line)
        if match:
            names.add(match.group(1))
    return names, None


def accepts_config(llc: Path, cfg: dict):
    """Compile an empty IR module with exactly this target's flags.

    IR, not MIR: `RET 0` is x86 spelling, and the point here is only that the
    triple plus feature list is accepted, not that a target-specific block
    verifies.
    """
    text = "define void @f() {\n  ret void\n}\n"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "probe.ll"
        path.write_text(text)
        argv = [str(llc), "-O0", "-mtriple=" + cfg["triple"],
                "-mattr=" + ",".join(cfg["mattr"]), *cfg.get("args", []),
                str(path), "-o", "-"]
        proc = subprocess.run(argv, capture_output=True, text=True)
        if proc.returncode == 0:
            return None
        return (proc.stderr.strip().splitlines() or ["rc=%d" % proc.returncode])[0]


def check(target: str, features_path: Path, llc: Path, mutate: str | None):
    configs = json.loads(CONFIGS.read_text())["targets"]
    if target not in configs:
        return ["no config table for target %r" % target]
    table = configs[target]
    names = load_features(features_path)
    problems = []
    for name in names:
        if name not in table:
            problems.append("%s: missing from data/mir-configs.json" % name)
            continue
        cfg = table[name]
        if "source" not in cfg:
            problems.append("%s: no source for the mapping" % name)
        if "mattr" not in cfg:
            continue
        if mutate == name:
            # The control has to break something the checker can *see*:
            # dropping a real feature leaves a valid (if narrower) config.
            cfg["mattr"] = ["not-a-real-subtarget-feature"]
        accepted, error = accepted_features(llc, cfg["triple"])
        if accepted is None:
            problems.append("%s: llc rejected triple %s: %s"
                            % (name, cfg["triple"], error))
            continue
        unknown = [f.lstrip("+-") for f in cfg["mattr"]
                   if f.lstrip("+-") not in accepted]
        if unknown:
            problems.append("%s: not a %s feature: %s"
                            % (name, cfg["triple"], ", ".join(unknown)))
        failure = accepts_config(llc, cfg)
        if failure:
            problems.append("%s: llc refused the config: %s" % (name, failure))
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mir-config-check")
    parser.add_argument("--target", required=True)
    parser.add_argument("--features", required=True)
    parser.add_argument("--llc",
                        default=str(Path.home() / "llvm/builds/explore/bin/llc"))
    parser.add_argument("--mutate", metavar="CONFIG",
                        help="break this config; the check must fail")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    problems = check(args.target, Path(args.features), Path(args.llc),
                     args.mutate)
    ok = not problems
    if args.json:
        print(json.dumps({"target": args.target, "mutated": args.mutate,
                          "ok": ok, "problems": problems}, indent=2))
    else:
        print("%s: %s" % (args.target, "ok" if ok else "%d problems"
                          % len(problems)))
        for problem in problems:
            print("  " + problem)
    if args.mutate:
        # The point of --mutate is that the check notices.
        return 0 if not ok else 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
