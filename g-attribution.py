#!/usr/bin/env python3
"""Attribute G-side disagreements back to the rulesets that carry the queries.

    g-attribution.py DIFF QUERIES EXPECT OUT

`EXPECT` is the JSON written by `inject-missing-opcode.py --expect`; the control
passes only when the diff disagrees, every disagreeing key is in the query file,
and every disagreeing ruleset belongs to the injected opcode's builder.

Unlike the U side, a G query's `ruleset` is the corpus's name for the builder
(e.g. `X_G_ADD`), so the expected set is derived from the queries that carry an
injected opcode, not from the opcode names themselves.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("u_attribution",
                                               ROOT / "u-attribution.py")
ua = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ua)


def main(argv) -> int:
    if len(argv) != 5:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    diff_path, queries_path, expect_path, out_path = map(Path, argv[1:])
    diff = json.loads(diff_path.read_text())
    expect = json.loads(expect_path.read_text())

    queries = {}
    for line in queries_path.read_text().splitlines():
        row = json.loads(line)
        for key in ua._expand_pointer_widths(ua.query_key(row)):
            queries[key] = row.get("ruleset", row["name"])

    injected = set(expect["opcodes"])
    allowed = {rs for key, rs in queries.items() if key[1] in injected}

    by_ruleset = Counter()
    unknown = []
    outside = set()
    for detail in diff.get("first_details", []):
        key = ua.query_key(detail["key_fields"])
        ruleset = queries.get(key)
        if ruleset is None:
            unknown.append(detail["key_fields"])
            continue
        by_ruleset[ruleset] += 1
        if ruleset not in allowed:
            outside.add(ruleset)

    report = {
        "disagree": diff.get("disagree", 0),
        "by_ruleset": dict(sorted(by_ruleset.items())),
        "unknown_keys": len(unknown),
        "expected_rulesets": sorted(allowed),
        "covered_expected": sorted(set(by_ruleset) & allowed),
        "outside_expected": sorted(outside),
    }
    out_path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(json.dumps(report, indent=1, sort_keys=True))

    if len(diff.get("first_details", [])) < diff.get("disagree", 0):
        print("g-attribution: diff truncated to %d of %d disagreements; "
              "re-run diff.py with a larger --details"
              % (len(diff.get("first_details", [])), diff.get("disagree", 0)),
              file=sys.stderr)
        return 2
    if report["disagree"] < 1:
        print("g-attribution: negative control produced no disagreement",
              file=sys.stderr)
        return 1
    if unknown:
        print("g-attribution: %d disagreeing keys are not in the query file"
              % len(unknown), file=sys.stderr)
        return 1
    if outside:
        print("g-attribution: disagreement outside injected rulesets: %s"
              % ", ".join(sorted(outside)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
