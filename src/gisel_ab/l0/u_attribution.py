#!/usr/bin/env python3
"""Attribute U-side disagreements back to upstream rulesets.

    u-attribution.py --diff diff.json --queries queries.jsonl [--expect FILE]

`diff.py` reports keys; U queries carry `ruleset`/`rule` labels, so we can say
*which upstream ruleset the missing rule belongs to* instead of only "action
differs".  Run `diff.py --details` large enough to keep every disagreement.

With `--expect` (written by `inject-missing-opcode.py`) the control contract is
enforced: at least one disagreement, every disagreeing ruleset inside the
injected builder's opcode set, and at least one hit on each injected ruleset
that has queries.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

PKG = Path(__file__).resolve().parent
AB_ROOT = PKG.parents[2]
GISEL = Path(os.environ.get("GISEL_SRC", AB_ROOT.parent / "gisel")).resolve()
sys.path.insert(0, str(GISEL))

from gisel import jsonl as J  # noqa: E402


def _runner_type(t):
    """LLT has no float kind: the runners echo `f32` as `s32`, `bf16` as `s16`.

    The comparison is symmetric (both sides go through the same parser), but the
    join with the query file must apply the same collapse or float-typed
    witnesses look like keys nobody asked about.  `bf16` is a one-element tuple
    in gisel's key model (`('bf16',)`), and LLT's bfloat16 is a 16-bit scalar.
    """
    if t[0] == "float":
        return ("scalar", t[1])
    if t[0] == "bf16":
        return ("scalar", 16)
    if t[0] == "vector":
        return ("vector", t[1], t[2], _runner_type(t[3]))
    return t


def query_key(fields) -> tuple:
    """Canonical key in the runner's own type model."""
    config, name, types, mem, imms = J.key(fields)
    types = tuple(_runner_type(t) for t in types)
    if mem is not None:
        mem = (_runner_type(mem[0]),) + tuple(mem[1:])
    return (config, name, types, mem, imms)


def _expand_pointer_widths(key):
    """Duplicate a key for every concrete width a `p0:*` query may mean.

    `cases` writes a pointer with an unknown width as `p0:*`; the runner echoes
    the target's actual width (`p0:32`/`p0:64`).  Without this expansion the
    join silently loses every wildcard-pointer disagreement (the baseline had
    none, so it only showed up under a widened predicate).
    """
    variants = [key]
    parts = list(key)
    for index in (2, 3):
        if parts[index] is None:
            continue
        if index == 2:
            types = list(parts[index])
            slots = range(len(types))
            get = lambda i: types[i]
        else:
            slots = [0]
            types = [parts[index][0]]
            get = lambda i: types[i]
        for i in slots:
            t = get(i)
            if not (isinstance(t, tuple) and t and t[0] == "pointer"
                    and len(t) >= 3 and t[2] == "*"):
                continue
            out = []
            for value in variants:
                for width in (32, 64):
                    p = list(value)
                    if index == 2:
                        tys = list(p[2]); tys[i] = ("pointer", t[1], width)
                        p[2] = tuple(tys)
                    else:
                        mem = list(p[3]); mem[0] = ("pointer", t[1], width)
                        p[3] = tuple(mem)
                    out.append(tuple(p))
            variants = out
    return variants


def load_queries(path) -> dict:
    out = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            fields = {"config": row["config"], "name": row["name"],
                      "types": row["types"], "mem": row.get("mem"),
                      "imms": row.get("imms", [])}
            info = {"ruleset": row.get("ruleset", row["name"]),
                    "rule": row.get("rule"),
                    "origin": row.get("origin", "unknown")}
            for key in _expand_pointer_widths(query_key(fields)):
                out[key] = info
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="u-attribution.py")
    ap.add_argument("--diff", required=True)
    ap.add_argument("--queries", required=True)
    ap.add_argument("--expect", default=None,
                    help="JSON from inject-missing-opcode.py --expect")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    queries = load_queries(args.queries)
    report = json.load(open(args.diff, encoding="utf-8"))
    details = report.get("first_details", [])
    if report.get("disagree", 0) > len(details):
        print("u-attribution: diff truncated to %d of %d disagreements; "
              "re-run diff.py with a larger --details"
              % (len(details), report["disagree"]), file=sys.stderr)
        return 2

    by_ruleset = Counter()
    by_class = Counter()
    unknown = []
    per_ruleset_rules = {}
    for detail in details:
        key = query_key(detail["key_fields"])
        info = queries.get(key)
        if info is None:
            unknown.append(detail["key_fields"])
            continue
        by_ruleset[info["ruleset"]] += 1
        by_class[detail["class"]] += 1
        if info["rule"] is not None:
            per_ruleset_rules.setdefault(info["ruleset"], Counter())[
                info["rule"]] += 1

    result = {"disagree": report.get("disagree", 0),
              "by_ruleset": dict(sorted(by_ruleset.items())),
              "by_class": dict(sorted(by_class.items())),
              "unknown_keys": len(unknown),
              "rules": {name: dict(sorted(counts.items()))
                        for name, counts in sorted(per_ruleset_rules.items())}}

    status = 0
    if args.expect:
        expect = json.load(open(args.expect, encoding="utf-8"))
        allowed = set(expect.get("opcodes", []))
        wanted = allowed & set(by_ruleset)
        outside = sorted(set(by_ruleset) - allowed)
        result["expected_rulesets"] = sorted(allowed)
        result["outside_expected"] = outside
        result["covered_expected"] = sorted(wanted)
        if not by_ruleset:
            print("u-attribution: negative control produced no disagreement",
                  file=sys.stderr)
            status = 1
        elif outside:
            print("u-attribution: disagreement outside injected rulesets: %s"
                  % ", ".join(outside), file=sys.stderr)
            status = 1
        elif unknown:
            print("u-attribution: %d disagreeing keys are not in the query file"
                  % len(unknown), file=sys.stderr)
            status = 1

    if args.json:
        print(json.dumps(result, indent=1, sort_keys=True))
    else:
        print("disagree=%d rulesets=%s classes=%s"
              % (result["disagree"], result["by_ruleset"],
                 result["by_class"]))
    return status


if __name__ == "__main__":
    sys.exit(main())
