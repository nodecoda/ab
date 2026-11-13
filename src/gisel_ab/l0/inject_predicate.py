#!/usr/bin/env python3
"""Mutate one rule predicate in a generated include (negative control).

    inject-predicate.py INC OPCODE MODE OUT [--rule N] [--expect FILE]

MODE:
  widen   drop one top-level `&&` conjunct (or `true` when there is none), so
          the rule matches strictly more queries;
  narrow  append `&& false`, so the rule matches nothing.

This is the predicate-level sibling of `inject-missing-opcode.py`: the opcode's
builder chain stays intact, only one predicate lambda in it changes.  `--rule`
selects the N-th `core*` predicate in the statement (default 0), so a caller
can pick a rule that the baseline query set actually witnesses.

Exit 2 when the opcode is absent/ambiguous or the statement has no predicate.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "inject_missing_opcode", PKG / "inject_opcode.py")
im = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(im)

START = im.START
PRED = re.compile(
    r"\.(core[A-Za-z]+)\(\s*(?:\[=\]|\[\])?\(const LegalityQuery &(?:Query)?\)"
    r"\s*\{\s*return\s+(.*?);\s*\}")


def _widen(expr: str) -> str:
    """Drop the first top-level conjunct, or make the predicate unconditional."""
    depth = 0
    for i in range(len(expr) - 1):
        ch = expr[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and expr.startswith("&&", i):
            left = expr[:i].strip()
            right = expr[i + 2:].strip()
            if left and right:
                return "(%s) || (%s)" % (left, right) if False else left
    return "true"


def _narrow(expr: str) -> str:
    return "(%s) && false" % expr if expr.strip() else "false"


def main(argv) -> int:
    args = list(argv[1:])
    rule_index = 0
    expect = None
    for flag in ("--rule", "--expect"):
        if flag in args:
            i = args.index(flag)
            value = args[i + 1]
            del args[i:i + 2]
            if flag == "--rule":
                rule_index = int(value)
            else:
                expect = Path(value)
    if len(args) != 4:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    source, opcode, mode, out = (Path(args[0]), args[1], args[2],
                                 Path(args[3]))
    if mode not in ("widen", "narrow"):
        print("inject: unknown mode %r (widen|narrow)" % mode, file=sys.stderr)
        return 2
    text = source.read_text(encoding="utf-8")

    hits = []
    for match in re.finditer(re.escape(START), text):
        end = im._statement_end(text, match.start())
        i = match.start() + len(START)
        while i < end and text[i].isspace():
            i += 1
        if i >= end or text[i] != "(":
            continue
        close = im._matching(text, i, "(", ")")
        if close < 0:
            continue
        arg = text[i + 1:close].strip()
        if arg.startswith("{"):
            inner = arg[arg.index("{") + 1:arg.rindex("}")]
            names = [n.strip() for n in inner.split(",")]
        else:
            names = [arg]
        names = [n for n in names if n]
        if opcode in names:
            hits.append((match.start(), end, names))
    if not hits:
        print("inject: %s does not build %s" % (source, opcode), file=sys.stderr)
        return 2
    if len(hits) > 1:
        print("inject: %s builds %s %d times; pick one builder"
              % (source, opcode, len(hits)), file=sys.stderr)
        return 2

    start, end, names = hits[0]
    body = text[start:end]
    preds = list(PRED.finditer(body))
    if not preds:
        print("inject: %s has no core predicate in the %s builder"
              % (source, opcode), file=sys.stderr)
        return 2
    if rule_index == -1:
        # The first predicate that is not literally `true`: `legalFor`-style
        # chains start with unconditional min/max rules, which a widen cannot
        # change.
        choices = [i for i, p in enumerate(preds) if p.group(2).strip() != "true"]
        if not choices:
            print("inject: %s has no non-trivial predicate in the %s builder"
                  % (source, opcode), file=sys.stderr)
            return 2
        rule_index = choices[0]
    if not 0 <= rule_index < len(preds):
        print("inject: rule %d out of range (builder has %d predicates)"
              % (rule_index, len(preds)), file=sys.stderr)
        return 2
    m = preds[rule_index]
    expr = m.group(2)
    changed = _widen(expr) if mode == "widen" else _narrow(expr)
    new_body = body[:m.start(2)] + changed + body[m.end(2):]
    patched = text[:start] + new_body + text[end:]
    out.write_text(patched, encoding="utf-8")
    if expect is not None:
        expect.write_text(json.dumps({
            "target_opcode": opcode, "opcodes": names, "mode": mode,
            "rule": rule_index, "action": m.group(1),
            "predicate_before": expr, "predicate_after": changed,
        }, indent=2) + "\n", encoding="utf-8")
    print("inject: %s %s rule %d (%s) in %s"
          % (opcode, mode, rule_index, m.group(1), source))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
