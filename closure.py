#!/usr/bin/env python3
"""Successor closure of the answer function: the multi-step evidence.

    closure.py --target x86 --seed SEED.jsonl --official RUN --ours RUN --out DIR

The one-step A/B says `getAction(q)` is equal for every `q` in a fixed set.  A
legalize loop applies that answer's mutation and asks again.  The loop is
therefore equal for every starting point whose whole successor chain stays
inside the tested set, and only there.

This script makes that condition checkable: it starts from a seed query set,
asks both runners, takes every non-terminal answer's `new_type`, and feeds the
resulting state back in as a new query.  It stops when no unseen state appears.
The output is the set of states that the loop can actually visit, the answers
both sides gave for each, and the counts that make "no disagreement" mean
something (terminal, unanswerable, stuck, revisited).

The seed is the rule-aware `cases` set: its classes are the representative
points of the answer partition, so starting from it is not a sample of the
initial states, it is the initial states.  Successors are not assumed to be in
that set; they are added until the set is closed.

Agreement of one step plus agreement of the successor function means agreement
of the whole loop by induction.  What this does *not* cover is written in
`docs/CLOSURE.md`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gisel"))
from gisel import jsonl as J  # noqa: E402

import ab  # noqa: E402

# spec/cases-format.md: these stop the loop.  Everything else mutates a type.
TERMINAL = frozenset({"Legal", "Lower", "Libcall", "Custom", "Unsupported"})


def rows(path: Path) -> list[dict]:
    out = []
    with Path(path).open() as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError as exc:
                raise SystemExit("%s:%d: %s" % (path, lineno, exc))
    return out


def index(path: Path) -> dict:
    got = {}
    for row in rows(path):
        got[J.key(row)] = row
    return got


def successor(query: dict, answer: dict):
    """The state the loop asks about next, or None when the loop stops.

    Returns (query, None) for a successor, (None, reason) when the loop does
    not continue: terminal action, no mutation, unanswerable, or a mutation
    that does not change the type (`stuck`, not progress).
    """
    if answer.get("status") == "unanswerable":
        return None, "unanswerable"
    action = answer.get("action")
    if action in TERMINAL:
        return None, "terminal"
    new_type = answer.get("new_type")
    if not isinstance(new_type, str) or new_type == "LLT_invalid":
        return None, "no_mutation"
    idx = int(answer.get("type_idx", 0))
    types = list(query.get("types") or [])
    if not 0 <= idx < len(types):
        return None, "bad_type_idx"
    if types[idx] == new_type:
        return None, "stuck"
    follow = dict(query)
    follow["types"] = list(types)
    follow["types"][idx] = new_type
    return follow, None


def answer_row(answer: dict):
    if answer.get("status") == "unanswerable":
        return ("unanswerable",)
    return (answer.get("action"), int(answer.get("type_idx", 0)),
            answer.get("new_type"))


def run(runner: Path, queries: Path, out: Path) -> None:
    subprocess.run([sys.executable, str(ROOT / "run-queries.py"),
                    str(runner), str(queries), str(out)], check=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="closure")
    parser.add_argument("--target", required=True)
    parser.add_argument("--seed", required=True, type=Path)
    parser.add_argument("--official", required=True, type=Path)
    parser.add_argument("--ours", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--max-states", type=int, default=5_000_000,
                        help="stop before the state set grows past this")
    parser.add_argument("--allow-ref-asserts", type=int, default=0,
                        help="pin the exact number of states where only the "
                             "official runner asserts")
    parser.add_argument("--max-rounds", type=int, default=64)
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)

    seen: dict = {}
    for row in rows(args.seed):
        seen.setdefault(J.key(row), row)
    frontier = list(seen.values())
    if not frontier:
        raise SystemExit("empty seed: %s" % args.seed)

    report = {
        "target": args.target,
        "seed": str(args.seed),
        "seed_states": len(frontier),
        "runners": {"official": str(args.official), "ours": str(args.ours)},
        "rounds": [],
        "answers": {},
        "edges": {"successors": 0, "revisited": 0, "stuck": 0},
        "disagree": [],
        "ok": False,
    }
    terminal_counts: dict = {}
    reasons: dict = {}
    unanswerable = {"both": 0, "ref_only": 0, "ours_only": 0}

    round_no = 0
    while frontier:
        if round_no >= args.max_rounds:
            report["stopped"] = "max-rounds"
            break
        if len(seen) > args.max_states:
            report["stopped"] = "max-states"
            break
        round_no += 1
        prefix = args.out / ("r%03d" % round_no)
        queries = prefix.with_suffix(".queries.jsonl")
        ref_out = prefix.with_suffix(".ref.jsonl")
        ours_out = prefix.with_suffix(".ours.jsonl")
        with queries.open("w") as handle:
            for row in frontier:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        run(args.official, queries, ref_out)
        run(args.ours, queries, ours_out)
        ref = index(ref_out)
        ours = index(ours_out)

        disagree = []
        new_frontier = []
        one_sided = []
        for query in frontier:
            key = J.key(query)
            a_ref, a_ours = ref.get(key), ours.get(key)
            if a_ref is None or a_ours is None:
                disagree.append({"key": repr(key), "why": "missing answer"})
                continue
            if a_ref.get("status") == "unanswerable" and \
                    a_ours.get("status") == "unanswerable":
                unanswerable["both"] += 1
                reasons["unanswerable"] = reasons.get("unanswerable", 0) + 1
                continue
            if a_ref.get("status") == "unanswerable" or \
                    a_ours.get("status") == "unanswerable":
                side = "ref" if a_ref.get("status") == "unanswerable" else "ours"
                unanswerable[side + "_only"] += 1
                if len(one_sided) < 20:
                    one_sided.append({"key": repr(key), "asserting": side})
                continue
            if answer_row(a_ref) != answer_row(a_ours):
                disagree.append({"key": repr(key), "why": "answer",
                                 "ref": answer_row(a_ref),
                                 "ours": answer_row(a_ours)})
                continue
            action = a_ours.get("action")
            terminal_counts[action] = terminal_counts.get(action, 0) + 1
            follow, why = successor(query, a_ours)
            if follow is None:
                reasons[why] = reasons.get(why, 0) + 1
                if why == "stuck":
                    report["edges"]["stuck"] += 1
                continue
            report["edges"]["successors"] += 1
            key_follow = J.key(follow)
            if key_follow in seen:
                report["edges"]["revisited"] += 1
                continue
            seen[key_follow] = follow
            new_frontier.append(follow)

        report["rounds"].append({
            "round": round_no,
            "asked": len(frontier),
            "new_states": len(new_frontier),
            "disagree": len(disagree),
            "one_sided": len(one_sided),
        })
        report.setdefault("one_sided", []).extend(one_sided)
        if disagree:
            report["disagree"].extend(disagree)
            report["stopped"] = "disagree"
            break
        frontier = new_frontier

    report["states"] = {"seed": len(rows(args.seed)),
                        "total": len(seen),
                        "added": len(seen) - report["seed_states"]}
    report["answers"] = {"terminal": dict(sorted(terminal_counts.items())),
                         "reasons": dict(sorted(reasons.items())),
                         "unanswerable": unanswerable}
    report["ok"] = (not report["disagree"]
                    and unanswerable["ref_only"] == args.allow_ref_asserts
                    and unanswerable["ours_only"] == 0)
    (args.out / "closure.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")

    print("target %s: %d states (%d seed + %d reached), %d rounds"
          % (args.target, report["states"]["total"], report["states"]["seed"],
             report["states"]["added"], len(report["rounds"])))
    print("edges: %d successors, %d revisited, %d stuck"
          % (report["edges"]["successors"], report["edges"]["revisited"],
             report["edges"]["stuck"]))
    print("unanswerable: both %d, ref-only %d, ours-only %d"
          % (unanswerable["both"], unanswerable["ref_only"],
             unanswerable["ours_only"]))
    print("disagree: %d" % len(report["disagree"]))
    if not report["ok"] and not report["disagree"]:
        print("pinned counts do not match: ref-only %d (want %d), ours-only %d "
              "(want 0)" % (unanswerable["ref_only"],
                            args.allow_ref_asserts, unanswerable["ours_only"]))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
