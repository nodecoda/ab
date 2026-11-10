#!/usr/bin/env bash
set -euo pipefail

# verify-evidence.sh [DIRECTION]
#
# Re-check the recorded A/B evidence: every artifact still hashes to what
# EVIDENCE.json says, every diff still reports the recorded summary, and every
# negative control still attributes all of its disagreements to the rulesets it
# injected.
#
#   DIRECTION   G | G-neg | U | U-neg   (default: all)
#
# The artifacts themselves live under /tmp and are not committed.  A missing
# artifact is a failure, not a skip: the manifest records the command that
# regenerates it.  Exit 1 on the first failing entry (after reporting all).

HERE=$(cd "$(dirname "$0")" && pwd)
exec python3 - "$HERE/EVIDENCE.json" "${1:-all}" <<'PY'
import gzip
import hashlib
import json
import pathlib
import sys

manifest_path, want = sys.argv[1], sys.argv[2]
manifest = json.loads(pathlib.Path(manifest_path).read_text())
oracle_root = pathlib.Path(manifest_path).parent / "oracle"

def fail(entry, message):
    print("FAIL %-16s %s" % (entry["id"], message))
    return 1

def resolve(entry, name, path=None):
    """The live artifact, else the frozen .gz, else None.

    `ab/freeze-oracle.sh` writes `oracle/<id>/<name>.gz`; the fallback keeps the
    same sha256 because verify reads the decompressed bytes.
    """
    d = pathlib.Path(entry["dir"])
    candidates = []
    if path is not None:
        candidates.append(pathlib.Path(path))
    candidates.append(d / name)
    candidates.append(d / (name + ".gz"))
    frozen = oracle_root / entry["id"]
    candidates.append(frozen / name)
    candidates.append(frozen / (name + ".gz"))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None

def read(path):
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data

def check(entry):
    d = pathlib.Path(entry["dir"])
    bad = 0

    for name, expected in entry["artifacts"].items():
        path = resolve(entry, name)
        if path is None:
            bad += fail(entry, "missing %s (re-run: %s)" % (d / name, entry["command"]))
            continue
        got = hashlib.sha256(read(path)).hexdigest()
        if got != expected:
            bad += fail(entry, "%s sha256 %s != %s" % (name, got[:16], expected[:16]))
    if bad:
        return bad

    # A runner links the target's CodeGen library at run time, so the answer
    # file is a function of that object as much as of the source.  A changed
    # library is not a hash failure (the artifacts still match what was
    # recorded), but it means the evidence no longer reproduces from the
    # current build: say so instead of staying silent.
    runtime = entry.get("runtime")
    if runtime:
        path = pathlib.Path(runtime["path"])
        if not path.exists():
            print("WARN %-16s runtime missing: %s" % (entry["id"], path))
        else:
            got = hashlib.sha256(path.read_bytes()).hexdigest()
            if got != runtime["sha256"]:
                print("WARN %-16s runtime %s changed (%s != %s)"
                      % (entry["id"], path.name, got[:16],
                         runtime["sha256"][:16]))

    queries = entry.get("queries")
    if queries:
        path = resolve(entry, pathlib.Path(queries["path"]).name,
                       queries["path"])
        if path is None:
            bad += fail(entry, "missing queries %s" % queries["path"])
        else:
            got = hashlib.sha256(read(path)).hexdigest()
            if got != queries["sha256"]:
                bad += fail(entry, "queries sha256 %s != %s"
                            % (got[:16], queries["sha256"][:16]))
    if bad:
        return bad

    expect = entry["expect"]
    diff_path = resolve(entry, entry.get("diff", "diff.json"))
    diff = json.loads(read(diff_path).decode())

    if expect.get("answers_identical"):
        a = read(resolve(entry, "official.answers.jsonl"))
        b = read(resolve(entry, "ours.answers.jsonl"))
        if a != b:
            bad += fail(entry, "answer files differ (diff.json alone is not enough)")

    for key in ("agree", "disagree", "unanswerable", "ref_asserted"):
        if key in expect and diff.get(key) != expect[key]:
            bad += fail(entry, "%s=%r, expected %r" % (key, diff.get(key), expect[key]))

    summary_expect = expect.get("summary")
    if summary_expect:
        summary = json.loads(read(resolve(entry, "summary.json")).decode())
        for key, value in summary_expect.items():
            if summary.get(key) != value:
                bad += fail(entry, "summary %s=%r, expected %r"
                            % (key, summary.get(key), value))

    minimum = expect.get("min_disagree")
    if minimum is not None:
        if diff.get("disagree", 0) < minimum:
            bad += fail(entry, "disagree=%r, expected >= %d"
                        % (diff.get("disagree"), minimum))
        attribution = json.loads(read(resolve(entry, "attribution.json")).decode())
        if attribution.get("disagree") != diff.get("disagree"):
            bad += fail(entry, "attribution covers %r of %r disagreements"
                        % (attribution.get("disagree"), diff.get("disagree")))
        unknown = attribution.get("unknown_keys", 0)
        if unknown != expect.get("unknown_keys", 0):
            bad += fail(entry, "unknown_keys=%r (every disagreement must be attributed)"
                        % unknown)
        outside = attribution.get("outside_expected") or []
        if outside:
            bad += fail(entry, "disagreements outside the injected rulesets: %r" % outside)
        injected = set(expect.get("rulesets", []))
        seen = set((attribution.get("by_ruleset") or {}).keys())
        if seen and not seen <= injected:
            bad += fail(entry, "attributed to %r, injected %r" % (sorted(seen), sorted(injected)))

    if not bad:
        print("PASS %-16s %s" % (entry["id"], d if d.exists()
                                 else oracle_root / entry["id"]))
    return bad

total = failures = 0
for entry in manifest["entries"]:
    if want != "all" and entry["direction"] != want:
        continue
    total += 1
    failures += check(entry)

print("%d/%d entries pass" % (total - failures, total))
sys.exit(1 if failures else 0)
PY
