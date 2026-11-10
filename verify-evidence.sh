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
import hashlib
import json
import pathlib
import sys

manifest_path, want = sys.argv[1], sys.argv[2]
manifest = json.loads(pathlib.Path(manifest_path).read_text())

def fail(entry, message):
    print("FAIL %-16s %s" % (entry["id"], message))
    return 1

def check(entry):
    d = pathlib.Path(entry["dir"])
    bad = 0

    for name, expected in entry["artifacts"].items():
        path = d / name
        if not path.exists():
            bad += fail(entry, "missing %s (re-run: %s)" % (path, entry["command"]))
            continue
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != expected:
            bad += fail(entry, "%s sha256 %s != %s" % (name, got[:16], expected[:16]))
    if bad:
        return bad

    queries = entry.get("queries")
    if queries:
        path = pathlib.Path(queries["path"])
        if not path.exists():
            bad += fail(entry, "missing queries %s" % path)
        else:
            got = hashlib.sha256(path.read_bytes()).hexdigest()
            if got != queries["sha256"]:
                bad += fail(entry, "queries sha256 %s != %s"
                            % (got[:16], queries["sha256"][:16]))
    if bad:
        return bad

    expect = entry["expect"]
    diff = json.loads((d / "diff.json").read_text())

    if expect.get("answers_identical"):
        a = (d / "official.answers.jsonl").read_bytes()
        b = (d / "ours.answers.jsonl").read_bytes()
        if a != b:
            bad += fail(entry, "answer files differ (diff.json alone is not enough)")

    for key in ("agree", "disagree", "unanswerable", "ref_asserted"):
        if key in expect and diff.get(key) != expect[key]:
            bad += fail(entry, "%s=%r, expected %r" % (key, diff.get(key), expect[key]))

    minimum = expect.get("min_disagree")
    if minimum is not None:
        if diff.get("disagree", 0) < minimum:
            bad += fail(entry, "disagree=%r, expected >= %d"
                        % (diff.get("disagree"), minimum))
        attribution = json.loads((d / "attribution.json").read_text())
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
        print("PASS %-16s %s" % (entry["id"], d))
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
