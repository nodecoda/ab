#!/usr/bin/env python3
"""Compare two full-answer JSONL files: the A/B workbench verb.

    diff.py REF ANSWERS [--queries QUERIES.jsonl] [--json]
            [--compare action|full]

``--queries`` closes the truncation hole: the query file fed to both sides is
the denominator, so a key that neither answer file contains is a failure and a
key that an answer file contains but the query file does not is a failure.  A
plain two-file comparison can only compare the intersection; this flag makes
the full set explicit.

Exit codes: 0 = same queries, same answers; 1 = a disagreeing, missing, or
unexpected key; 2 = an unreadable line or a key with two different answers.  This is the workbench side of the boundary in
``docs/SCOPE.md``: the comparison lives here, not in ``gisel``, because it
exists to compare a reference implementation with ours.  Only the answer-file
reader is shared from ``gisel.answers``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

AB_ROOT = Path(__file__).resolve().parent
GISEL = Path(os.environ.get("GISEL_SRC", AB_ROOT.parent / "gisel")).resolve()
sys.path.insert(0, str(GISEL))

from gisel import jsonl as J  # noqa: E402


def _key_fields(key):
    config, name, types, mem, imms = key
    fields = {
        "config": config,
        "name": name,
        "types": [J.llt_text(t) for t in types],
        "mem": None,
        "imms": list(imms),
    }
    if mem is not None:
        fields["mem"] = [J.llt_text(mem[0]), mem[1], mem[2], mem[3]]
    return fields


def _classify(a, b):
    """Why two answers differ, coarsest first."""
    if a[0] != b[0]:
        return "status"
    if a[1] != b[1]:
        return "action"
    if a[2] != b[2]:
        return "type_idx"
    return "new_type"


def collect_keys(path):
    """Keys of a query file, plus row/error counts, without answer decoding.

    A query row has no ``action`` field, so ``J.load`` is the wrong reader
    here.  A malformed row is counted, not skipped silently.
    """
    keys = set()
    rows = 0
    errors = 0
    with open(path) as stream:
        for lineno, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            rows += 1
            try:
                keys.add(J.key(json.loads(line)))
            except (ValueError, KeyError, TypeError, J.EvalError) as exc:
                print("%s:%d: %s" % (path, lineno, exc), file=sys.stderr)
                errors += 1
    return keys, rows, errors


def compare(ref, ours, mode="full", details_limit=100,
            allow_ref_asserts=None, queries=None):
    """Full-set comparison: a key on one side only is a failure.

    ``mode="action"`` is the coarse smoke gate: it compares only the action
    name and deliberately ignores ``type_idx``/``new_type``.  ``mode="full"``
    is the acceptance comparison.  Unlike ``gisel cases --against``, which
    reports the overlap, this is the workbench contract "same queries, same
    answers".
    """
    if mode not in ("action", "full"):
        raise ValueError("unknown compare mode %r" % (mode,))
    answer_keys = set(ref) | set(ours)
    keys = sorted(answer_keys, key=repr)
    if queries is None:
        missing_in_both = unexpected = None
    else:
        missing_in_both = sorted(queries - answer_keys, key=repr)
        unexpected = sorted(answer_keys - queries, key=repr)
    matched = [k for k in keys if k in ref and k in ours]
    agree = 0
    unanswerable = 0
    disagree = []
    ref_asserted = []
    for k in matched:
        a, b = ref[k], ours[k]
        if (allow_ref_asserts is not None and a[0] == "unanswerable"
                and a[1] == "asserted" and b[0] == "answered"):
            # The reference asserted before answering and ours answered.  Only
            # counted as a known class when the caller pins how many to expect:
            # an unpinned assert is a difference, not a footnote.
            ref_asserted.append((k, a, b))
            continue
        same_unanswerable = (a[0] == b[0] == "unanswerable"
                             and a[1] == b[1])
        if mode == "action":
            same_answer = a[0] == b[0] == "answered" and a[1] == b[1]
        else:
            same_answer = (a[0] == b[0] == "answered"
                           and a[1] == b[1] and a[2] == b[2]
                           and J.values_equal(a[3], b[3]))
        if same_unanswerable or same_answer:
            agree += 1
            unanswerable += int(same_unanswerable)
        else:
            disagree.append((k, a, b))
    details = [
        {"key": repr(k), "key_fields": _key_fields(k),
         "class": _classify(a, b),
         "ref": list(a), "ours": list(b)}
        for k, a, b in disagree[:details_limit]
    ]
    # ``agree`` is "same observable result": answered-and-equal plus
    # both-unanswerable.  ``answered_equal`` is the strict count, so a reader
    # never has to subtract by hand.  The identity is the definition of
    # ``matched``; assert it here instead of trusting the loop above.
    answered_equal = agree - unanswerable
    accounted = agree + len(ref_asserted) + len(disagree)
    if accounted != len(matched):
        raise AssertionError(
            "answer accounting: agree(%d) + ref_asserted(%d) + disagree(%d)"
            " != matched(%d)" % (agree, len(ref_asserted), len(disagree),
                                 len(matched)))
    return {
        "mode": mode,
        "ref": len(ref),
        "ours": len(ours),
        "matched": len(matched),
        "agree": agree,
        "answered_equal": answered_equal,
        "unanswerable": unanswerable,
        "disagree": len(disagree),
        "ref_asserted": len(ref_asserted),
        "ref_asserted_keys": [repr(k) for k, _, _ in ref_asserted[:20]],
        "_ref_asserted_all": [k for k, _, _ in ref_asserted],
        "missing_ref": len(set(ours) - set(ref)),
        "missing_ours": len(set(ref) - set(ours)),
        "first": disagree[:20],
        "first_details": details,
        "missing_ref_keys": sorted(set(ours) - set(ref), key=repr)[:20],
        "missing_ours_keys": sorted(set(ref) - set(ours), key=repr)[:20],
        "query_count": None if queries is None else len(queries),
        "missing_in_both": None if queries is None else len(missing_in_both),
        "unexpected": None if queries is None else len(unexpected),
        "missing_in_both_keys": [] if queries is None else missing_in_both[:20],
        "unexpected_keys": [] if queries is None else unexpected[:20],
    }


def collect_sites(path):
    """key -> assert_site for an answer file, read without the strict loader.

    The site is provenance, not part of the answer: the comparison stays on
    (status, reason).  This is a separate pass so a run that never records a
    site costs nothing.
    """
    sites = {}
    with open(path) as f:
        for line in f:
            if '"assert_site"' not in line:
                continue
            row = json.loads(line)
            sites[J.key(row)] = row["assert_site"]
    return sites


def compare_sites(ref_sites, ours_sites, keys):
    same = {}
    mismatch = []
    missing = 0
    for k in keys:
        a = ref_sites.get(k)
        b = ours_sites.get(k)
        if a is None or b is None:
            missing += 1
            continue
        if a == b:
            same[a] = same.get(a, 0) + 1
        else:
            mismatch.append((k, a, b))
    return {
        "same": sum(same.values()),
        "mismatch": len(mismatch),
        "missing": missing,
        "top": sorted(same.items(), key=lambda kv: (-kv[1], kv[0]))[:10],
        "first_mismatch": [list(x) for x in mismatch[:10]],
    }


def _parse_assert_pin(value):
    """Parse ``--allow-ref-asserts``.

    ``N`` pins the total (the original form).  Anything else pins each site:

    ``A.h:12=3,B.cpp:200=18``  inline, comma separated, ``=`` splits count
    ``@file.json``             a JSON object ``{site: count}``

    Pinning by site is the point: a total of 30,150 can hide a new assert
    class that replaced an old one, because the number did not move.
    """
    if value is None:
        return None, None
    text = str(value).strip()
    if text.isdigit():
        return "total", int(text)
    if text.startswith("@"):
        with open(text[1:]) as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise SystemExit("assert-site pin must be a JSON object of site: count")
        return "sites", {str(k): int(v) for k, v in data.items()
                         if not str(k).startswith("_")}
    pins = {}
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        site, sep, count = item.rpartition("=")
        if not sep or not site or not count.isdigit():
            raise SystemExit(
                "cannot parse assert-site pin %r; use site=count" % item)
        pins[site] = int(count)
    return "sites", pins


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="diff.py",
        description="compare two full-answer JSONL files")
    ap.add_argument("ref")
    ap.add_argument("ours")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--queries", default=None, metavar="PATH",
                    help="query file fed to both sides; answers must cover "
                         "exactly its key set")
    ap.add_argument("--compare", choices=("action", "full"), default="full",
                    help="action: coarse smoke gate; full: acceptance")
    ap.add_argument("--details", type=int, default=100,
                    help="maximum first_details entries (default 100)")
    ap.add_argument("--allow-ref-asserts", default=None, metavar="N|SITES",
                    help="count the queries whose reference answer is "
                         "'asserted' as a known class, not a difference. "
                         "N pins the total; 'site=count,...' or '@file.json' "
                         "pins each assert site, so a new assert class cannot "
                         "hide behind an unchanged total")
    ap.add_argument("--assert-sites", action="store_true",
                    help="also compare where the two sides asserted "
                         "(needs answer files that carry assert_site)")
    ap.add_argument("--expect-unanswerable", type=int, default=None,
                    metavar="N",
                    help="fail unless exactly N queries are unanswerable on "
                         "both sides; pins a shared assert so a new class of "
                         "assert cannot hide in the unanswerable count")
    args = ap.parse_args(argv)

    ref, e1 = J.load(args.ref)
    ours, e2 = J.load(args.ours)
    query_keys = None
    query_rows = None
    qerrors = 0
    if args.queries:
        try:
            query_keys, query_rows, qerrors = collect_keys(args.queries)
        except OSError as exc:
            print("cannot read queries: %s" % exc, file=sys.stderr)
            return 2
    result = compare(ref, ours, args.compare, args.details,
                     args.allow_ref_asserts, query_keys)
    result["errors"] = e1 + e2 + qerrors
    if args.queries:
        result["query_rows"] = query_rows
    pin_mode, pin_value = _parse_assert_pin(args.allow_ref_asserts)
    ref_asserted_all = result.pop("_ref_asserted_all", [])
    ref_sites = collect_sites(args.ref) if (args.assert_sites or ref_asserted_all) else {}
    if ref_asserted_all:
        by_site, by_opcode = {}, {}
        for key in ref_asserted_all:
            site = ref_sites.get(key) or "<no-site>"
            by_site[site] = by_site.get(site, 0) + 1
            by_opcode[key[1]] = by_opcode.get(key[1], 0) + 1
        result["ref_asserted_by_site"] = dict(
            sorted(by_site.items(), key=lambda kv: (-kv[1], kv[0])))
        result["ref_asserted_by_opcode"] = dict(
            sorted(by_opcode.items(), key=lambda kv: (-kv[1], kv[0])))
    if args.assert_sites:
        both = [k for k in ref if k in ours and ref[k][0] == "unanswerable"
                and ours[k][0] == "unanswerable"]
        result["assert_sites"] = compare_sites(
            ref_sites, collect_sites(args.ours), both)
    if args.json:
        print(json.dumps(result, indent=1, sort_keys=True))
    else:
        print("mode=%s ref=%d ours=%d matched=%d agree=%d "
              "(answered_equal=%d unanswerable=%d) "
              "disagree=%d missing_ref=%d missing_ours=%d errors=%d"
              % (result["mode"], result["ref"], result["ours"],
                 result["matched"], result["agree"],
                 result["answered_equal"], result["unanswerable"],
                 result["disagree"], result["missing_ref"],
                 result["missing_ours"], result["errors"]))
        if args.queries:
            print("queries=%d missing_in_both=%d unexpected=%d"
                  % (result["query_count"], result["missing_in_both"],
                     result["unexpected"]))
        for key, a, b in result["first"]:
            print("MISMATCH %r: ref=%r ours=%r" % (key, a, b))
        if result.get("ref_asserted_by_site"):
            print("ref_asserted_by_site total=%d" % result["ref_asserted"])
            for site, count in list(result["ref_asserted_by_site"].items())[:5]:
                print("  %6d  %s" % (count, site))
        if "assert_sites" in result:
            sites = result["assert_sites"]
            print("assert_sites same=%d mismatch=%d missing=%d"
                  % (sites["same"], sites["mismatch"], sites["missing"]))
            for site, count in sites["top"][:5]:
                print("  %6d  %s" % (count, site))
        for key in result["missing_ref_keys"][:5]:
            print("MISSING in ref: %r" % (key,))
        for key in result["missing_ours_keys"][:5]:
            print("MISSING in ours: %r" % (key,))
    if result["errors"]:
        return 2
    if args.queries and (result["missing_in_both"] or result["unexpected"]):
        print("query set mismatch: queries=%d ref=%d ours=%d "
              "missing_in_both=%d unexpected=%d"
              % (result["query_count"], result["ref"], result["ours"],
                 result["missing_in_both"], result["unexpected"]),
              file=sys.stderr)
        return 1
    if (args.expect_unanswerable is not None
            and result["unanswerable"] != args.expect_unanswerable):
        print("both sides unanswerable on %d queries, expected %d"
              % (result["unanswerable"], args.expect_unanswerable),
              file=sys.stderr)
        return 1
    if pin_mode == "total" and result["ref_asserted"] != pin_value:
        print("ref asserted on %d queries, expected %d"
              % (result["ref_asserted"], pin_value), file=sys.stderr)
        return 1
    if pin_mode == "sites":
        got = result.get("ref_asserted_by_site", {})
        missing = {k: v for k, v in pin_value.items() if k not in got}
        extra = {k: v for k, v in got.items() if k not in pin_value}
        moved = {k: (pin_value[k], got[k]) for k in pin_value
                 if k in got and pin_value[k] != got[k]}
        if missing or extra or moved:
            print("ref assert sites do not match the pin", file=sys.stderr)
            for site, count in sorted(missing.items()):
                print("  missing  %-48s expected %d, seen 0" % (site, count),
                      file=sys.stderr)
            for site, count in sorted(extra.items()):
                print("  new      %-48s expected 0, seen %d" % (site, count),
                      file=sys.stderr)
            for site, (want, seen) in sorted(moved.items()):
                print("  moved    %-48s expected %d, seen %d"
                      % (site, want, seen), file=sys.stderr)
            return 1
    if (result["missing_ref"] or result["missing_ours"]
            or result["disagree"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
