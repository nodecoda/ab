#!/usr/bin/env python3
"""Offline suite check: our answers against a frozen official snapshot.

    suite.py check --target m68k [--json]
    suite.py check --all

No LLVM, no build, no network.  For each target under ``suite/`` this reads
the frozen answerless queries and the answers the official legalizer gave
when the snapshot was taken, generates the normal form with ``gisel gen``,
answers the same queries with ``gisel eval``, and compares the two answer
files with the same full-set contract the A/B harness uses.

A ``p0:*`` query is the one thing the frozen files cannot answer by
themselves: the width is a target property, and the compiled runner resolves
it per configuration before the legalizer sees it.  ``suite.json`` therefore
declares ``pointer_width`` per configuration.  ``check`` expands ``p0:*`` in
both the queries and the frozen answers before evaluation; a configuration
that has wildcard queries but no declared width is refused, not guessed.

What it proves: the corpus in `gisel` still reproduces the actions the
official legalizer produced on this query set -- rules, predicates and
evaluation semantics together.  What it does not prove: anything about
emitters, MIR, or queries outside the frozen set.  The pinned shas make both
statements checkable: if the corpus, the features or either file changes, the
suite refuses to run rather than compare different questions.

Exit codes: 0 every query agrees, 1 a disagreement, 2 the snapshot or the
environment is broken (drift, missing file, gisel cannot run).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parent
AB_ROOT = PKG.parents[1]
GISEL = Path(os.environ.get("GISEL_SRC", AB_ROOT.parent / "gisel")).resolve()
SUITE = PKG / "data" / "suite"

from gisel_ab.l0 import diff as differ  # noqa: E402

POINTER_WILDCARD = re.compile(r"p(\d+):\*")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class SuiteError(RuntimeError):
    pass


def targets() -> list[str]:
    return sorted(p.parent.name for p in SUITE.glob("*/suite.json"))


def load(target: str) -> tuple[dict, Path]:
    directory = SUITE / target
    manifest = directory / "suite.json"
    if not manifest.is_file():
        raise SuiteError("no suite for %r (have: %s)"
                         % (target, ", ".join(targets())))
    return json.loads(manifest.read_text()), directory


def _check_sha(directory: Path, doc: dict, key: str, relative: str) -> Path:
    path = directory / relative
    if not path.is_file():
        raise SuiteError("%s: %s is missing" % (directory.name, relative))
    got = sha256(path)
    want = doc.get(key)
    if want and got != want:
        raise SuiteError(
            "%s: %s drifted (sha256 %s, recorded %s); regenerate the snapshot "
            "and say why in the commit" % (directory.name, relative,
                                           got[:16], want[:16]))
    return path


def _gisel(*args: str, cwd: Path) -> None:
    env = dict(os.environ)
    parts = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    if str(GISEL) not in parts:
        env["PYTHONPATH"] = os.pathsep.join([str(GISEL), *parts])
    done = subprocess.run([sys.executable, "-m", "gisel", *args],
                          cwd=str(cwd), env=env, capture_output=True,
                          text=True)
    if done.returncode != 0:
        raise SuiteError("gisel %s failed: %s"
                         % (args[0], (done.stderr or done.stdout).strip()))


def _read_jsonl(path: Path) -> tuple[list[dict], list[str]]:
    rows, errors = [], []
    with open(path) as stream:
        for lineno, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                errors.append("%s:%d: %s" % (path, lineno, exc))
                continue
            if not isinstance(row, dict):
                errors.append("%s:%d: row is not an object" % (path, lineno))
                continue
            rows.append(row)
    return rows, errors


def _pointer_widths(doc: dict, target: str) -> dict[str, int]:
    table = doc.get("pointer_width", {})
    if not isinstance(table, dict):
        raise SuiteError("%s: pointer_width must be an object" % target)
    widths = {}
    for config, bits in table.items():
        if isinstance(bits, bool) or not isinstance(bits, int) or bits <= 0:
            raise SuiteError("%s: pointer_width[%r] must be a positive integer"
                             % (target, config))
        widths[str(config)] = bits
    return widths


def _has_wildcard(value) -> bool:
    if isinstance(value, str):
        return POINTER_WILDCARD.search(value) is not None
    if isinstance(value, (list, tuple)):
        return any(_has_wildcard(item) for item in value)
    return False


def _expand(value, bits: int):
    if isinstance(value, str):
        return POINTER_WILDCARD.sub(
            lambda match: "p%s:%d" % (match.group(1), bits), value)
    if isinstance(value, list):
        return [_expand(item, bits) for item in value]
    if isinstance(value, tuple):
        return tuple(_expand(item, bits) for item in value)
    return value


def _expand_row(row: dict, widths: dict[str, int]) -> dict:
    bits = widths.get(row.get("config"))
    if bits is None:
        return row
    out = dict(row)
    if "types" in out:
        out["types"] = _expand(out["types"], bits)
    if out.get("mem") is not None:
        out["mem"] = _expand(out["mem"], bits)
    if isinstance(out.get("new_type"), str):
        out["new_type"] = _expand(out["new_type"], bits)
    return out


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def _validate_configs(doc: dict, rows: list[dict], target: str) -> None:
    recorded = doc.get("configs")
    if recorded is None:
        return
    actual = sorted({row.get("config") for row in rows
                     if isinstance(row.get("config"), str)})
    if sorted(recorded) != actual:
        raise SuiteError("%s: manifest configs %r do not match the query file "
                         "(%r)" % (target, recorded, actual))


def _validate_pointer_widths(doc: dict, rows: list[dict],
                             target: str) -> dict[str, int]:
    widths = _pointer_widths(doc, target)
    need = {row.get("config") for row in rows
            if _has_wildcard(row.get("types"))
            or _has_wildcard(row.get("mem"))}
    missing = sorted(config for config in need if config not in widths)
    if missing:
        raise SuiteError(
            "%s: p0:* queries in %s, but suite.json has no pointer_width for "
            "them; the width is a target property and is not guessed"
            % (target, ", ".join(missing)))
    return widths


def _gisel_path(directory: Path, recorded: str) -> Path:
    """The corpus/features a snapshot was taken from.

    Snapshots record a path relative to their own directory.  That was
    ``../../../gisel/...`` when suite/ sat at the repository root; the data
    moved under ``src/gisel_ab/data/suite`` and the same spelling now resolves
    inside the package.  The file name is the part that identifies the input,
    so fall back to the gisel checkout by name.
    """
    path = (directory / recorded).resolve()
    if path.is_file():
        return path
    marker = recorded.replace("\\", "/")
    if "gisel/" in marker:
        return (GISEL / marker.split("gisel/", 1)[1]).resolve()
    return (GISEL / "tests" / "corpus" / Path(recorded).name).resolve()


def check(target: str, verbose: bool = False) -> dict:
    doc, directory = load(target)
    queries = _check_sha(directory, doc, "queries_sha256", doc["queries"])
    answers = _check_sha(directory, doc, "answers_sha256", doc["answers"])

    corpus = _gisel_path(directory, doc["corpus"])
    features = _gisel_path(directory, doc["features"])
    for label, path, key in (("corpus", corpus, "corpus_sha256"),
                             ("features", features, "features_sha256")):
        if not path.is_file():
            raise SuiteError("%s: %s is missing: %s" % (target, label, path))
        if doc.get(key) and sha256(path) != doc[key]:
            raise SuiteError(
                "%s: the %s changed since the snapshot (sha256 %s, recorded "
                "%s); the frozen answers describe the old rules"
                % (target, label, sha256(path)[:16], doc[key][:16]))

    query_rows, query_errors = _read_jsonl(queries)
    if query_errors:
        raise SuiteError("%s: %d unreadable query line(s): %s"
                         % (target, len(query_errors), query_errors[0]))
    _validate_configs(doc, query_rows, target)
    widths = _validate_pointer_widths(doc, query_rows, target)

    answer_rows, answer_errors = _read_jsonl(answers)
    if answer_errors:
        raise SuiteError("%s: %d unreadable answer line(s): %s"
                         % (target, len(answer_errors), answer_errors[0]))

    expanded_queries = [_expand_row(row, widths) for row in query_rows]
    expanded_answers = [_expand_row(row, widths) for row in answer_rows]

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        core = tmp / "core.json"
        frozen = tmp / "answers.jsonl"
        asked = tmp / "queries.jsonl"
        ours = tmp / "ours.answers.jsonl"
        _write_jsonl(asked, expanded_queries)
        _write_jsonl(frozen, expanded_answers)
        _gisel("gen", str(corpus), "--emit=core", "--out", str(core), cwd=tmp)
        _gisel("eval", "--doc", str(core), "--features", str(features),
               "--cases", str(asked), "--answers", str(ours), cwd=tmp)

        ref = _load_answers(frozen)
        got = _load_answers(ours)
        query_keys, rows, errors = differ.collect_keys(asked)
        if errors or rows != doc.get("query_count", rows):
            raise SuiteError("%s: query file has %d rows (%d unreadable), the "
                             "manifest says %s"
                             % (target, rows, errors, doc.get("query_count")))
        result = differ.compare(ref, got, "full", 10, None, query_keys)

    result["target"] = target
    result["query_count"] = rows
    expected_unanswerable = doc.get("allow_unanswerable")
    if expected_unanswerable is not None and \
            result["unanswerable"] != expected_unanswerable:
        result["unanswerable_drift"] = (
            "expected %d, got %d" % (expected_unanswerable,
                                     result["unanswerable"]))
    if verbose:
        result["first"] = [[repr(k), a, b] for k, a, b in result["first"]]
    return result


def _load_answers(path: Path) -> dict:
    from gisel import jsonl as J
    answers, errors = J.load(str(path))
    if errors:
        raise SuiteError("%s: %d unreadable answer line(s)" % (path, errors))
    return answers


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="suite.py",
        description="compare our rules with a frozen official snapshot; "
                    "no LLVM")
    sub = ap.add_subparsers(dest="command", required=True)
    chk = sub.add_parser("check", help="answer the frozen queries again")
    chk.add_argument("--target", action="append", dest="targets")
    chk.add_argument("--all", action="store_true")
    chk.add_argument("--json", action="store_true")
    chk.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    picked = args.targets or []
    if args.all:
        picked = targets()
    if not picked:
        ap.error("give --target NAME or --all")
    missing = [t for t in picked if not (SUITE / t / "suite.json").is_file()]
    if missing:
        print("suite.py: no suite for %s (have: %s)"
              % (", ".join(missing), ", ".join(targets())), file=sys.stderr)
        return 2

    results = []
    failed = 0
    for target in picked:
        try:
            result = check(target, verbose=args.verbose)
        except SuiteError as exc:
            print("suite.py: %s" % exc, file=sys.stderr)
            return 2
        results.append(result)
        bad = (result["disagree"] or result["missing_ref"]
               or result["missing_ours"] or result.get("unanswerable_drift"))
        failed += 1 if bad else 0
        if not args.json:
            print("%s: queries=%d agree=%d disagree=%d missing_ref=%d "
                  "missing_ours=%d unanswerable=%d %s"
                  % (target, result["query_count"], result["agree"],
                     result["disagree"], result["missing_ref"],
                     result["missing_ours"], result["unanswerable"],
                     "FAIL" if bad else "ok"))
            for key, a, b in result["first"][:3]:
                print("  MISMATCH %s: ref=%r ours=%r"
                      % (key if isinstance(key, str) else repr(key), a, b))
            if result.get("unanswerable_drift"):
                print("  unanswerable drift: %s" % result["unanswerable_drift"])

    if args.json:
        print(json.dumps({"ok": failed == 0, "results": results},
                         indent=1, sort_keys=True, default=str))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
