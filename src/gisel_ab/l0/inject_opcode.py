#!/usr/bin/env python3
"""Neutralise one opcode's rules in a generated include (negative control).

    inject-missing-opcode.py INC OPCODE OUT

The include is a chain of `getActionDefinitionsBuilder({...}).legalFor(...)`
statements.  We find the statement whose opcode set contains OPCODE and replace
the whole chain with `.unsupported()`, so every query for that ruleset answers
Unsupported on our side.  The ruleset stays registered (removing the statement
entirely would leave `getActionDefinitions` with nothing to return).

Exit 2 when the opcode is not present or is built more than once (ambiguous).

Why ruleset-level and not one rule: the generated include is a builder chain,
so individual rule identity is gone by construction.  Dropping one rule's
predicate by hand would test the injector, not the diff.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

START = "getActionDefinitionsBuilder"


def _matching(text: str, start: int, opener: str, closer: str) -> int:
    """Index of the `closer` that balances the `opener` at `start` (-1 if none)."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _statement_end(text: str, start: int) -> int:
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        elif ch == ";" and depth == 0:
            return i + 1
        i += 1
    raise SystemExit("inject: unterminated statement at offset %d" % start)


def main(argv) -> int:
    args = list(argv[1:])
    expect = None
    if "--expect" in args:
        index = args.index("--expect")
        expect = Path(args[index + 1])
        del args[index:index + 2]
    if len(args) != 3:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    source, opcode, out = Path(args[0]), args[1], Path(args[2])
    text = source.read_text(encoding="utf-8")

    hits = []
    for match in re.finditer(re.escape(START), text):
        end = _statement_end(text, match.start())
        # The opcodes are the argument of the builder call itself.  A builder
        # may name one opcode (`getActionDefinitionsBuilder(G_ICMP)`) or a set
        # (`getActionDefinitionsBuilder({G_ADD, G_SUB})`); the first brace in
        # the statement belongs to `.legalFor` in the single-opcode case, so
        # it cannot be used to find the set.
        i = match.start() + len(START)
        while i < end and text[i].isspace():
            i += 1
        if i >= end or text[i] != "(":
            continue
        close = _matching(text, i, "(", ")")
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
        print("inject: %s builds %s %d times; pick an opcode with one builder"
              % (source, opcode, len(hits)), file=sys.stderr)
        return 2

    start, end, names = hits[0]
    # `getActionDefinitionsBuilder({X})` is rejected upstream (it wants at least
    # two opcodes in the braced form), so a singleton keeps the bare spelling.
    if len(names) == 1:
        call = START + "(" + names[0] + ")"
    else:
        call = START + "({" + ", ".join(names) + "})"
    patched = text[:start] + call + ".unsupported();" + text[end:]
    out.write_text(patched, encoding="utf-8")
    if expect is not None:
        expect.write_text(json.dumps({"target_opcode": opcode,
                                      "opcodes": names}, indent=2) + "\n",
                          encoding="utf-8")
    print("inject: %s -> unsupported in %s (%d -> %d bytes); rulesets %s"
          % (opcode, source, len(text), len(patched), ", ".join(names)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
