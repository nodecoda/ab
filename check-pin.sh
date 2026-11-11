#!/usr/bin/env bash
set -euo pipefail

# check-pin.sh TREE [PIN]
#
# The official side of the A/B harness is not bare upstream: it is the pin
# commit plus the unmerged PRs listed in PIN.json `patches`.  The corpus
# deliberately encodes the post-patch behaviour, so a tree that lacks one of
# those commits makes the official runner answer with pre-patch rules and every
# covered query shows up as a disagreement that looks like a translation error.
#
# Ancestry alone is not enough.  `pin` being an ancestor plus every patch being
# present also passes a fork branch with extra local commits, and those commits
# can change answers without being declared.  That is not hypothetical: a local
# `getNumElements()` hardening in AArch64LegalizerInfo.cpp answered queries the
# pin asserts on, and the ancestry check still said "pin check: ok".
#
# So the check is content based.  PIN.json `official_base.files` records the
# sha256 of every file whose content can change legalizer answers, taken from
# the exact tree the official library was built from.  The official side is
# frozen there: a tree passes only if all of those files match byte for byte.
# See docs/OFFICIAL-BASE.md for what is frozen, what the declared deviations
# are, and what it costs to change it.

TREE=${1:?usage: check-pin.sh TREE [PIN]}
. "$(cd "$(dirname "$0")" && pwd)/env.sh"
PIN=${2:-${GS_PIN:-$ROOT/../upstream-source/pin/PIN.json}}

if [ "${GIT_DSL_SKIP_PIN_CHECK:-}" = "1" ]; then
  echo "pin check: skipped by GIT_DSL_SKIP_PIN_CHECK=1" >&2
  exit 0
fi

python3 - "$TREE" "$PIN" <<'PY'
import json, hashlib, os, subprocess, sys

tree, pin_path = sys.argv[1], sys.argv[2]
pin = json.load(open(pin_path))
base = pin["commit"]
base_map = pin.get("official_base", {}).get("files")

def git(*args):
    return subprocess.run(["git", "-C", tree] + list(args),
                          capture_output=True, text=True)

def git_ok(*args):
    return git(*args).returncode == 0

has_git = git_ok("rev-parse", "--git-dir")
head = git("rev-parse", "--short=12", "HEAD").stdout.strip() if has_git else "no-git"
branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() if has_git else "-"

if base_map is None:
    # Backward compatibility: a PIN.json without the content map can only be
    # checked by ancestry.  Say so instead of pretending it is a full check.
    if not has_git:
        print("pin check: %s has no official_base map and no git metadata" % tree,
              file=sys.stderr)
        sys.exit(1)
    missing = []
    if not git_ok("merge-base", "--is-ancestor", base, "HEAD"):
        missing.append((base, "the pin commit itself"))
    for p in pin.get("patches", []):
        if not git_ok("merge-base", "--is-ancestor", p["commit"], "HEAD"):
            missing.append((p["commit"], "#%s %s" % (p["pr"], p["title"])))
    if missing:
        print("pin check: %s (%s) cannot back the corpus." % (head, branch),
              file=sys.stderr)
        for commit, what in missing:
            print("  missing %s  %s" % (commit, what), file=sys.stderr)
        sys.exit(1)
    print("pin check: ancestry only (PIN.json has no official_base map) at %s"
          % head, file=sys.stderr)
    sys.exit(0)

bad = []
for rel, expected in sorted(base_map.items()):
    path = os.path.join(tree, rel)
    if not os.path.exists(path):
        bad.append((rel, expected, "missing"))
        continue
    actual = hashlib.sha256(open(path, "rb").read()).hexdigest()
    if actual != expected:
        bad.append((rel, expected, actual))

if not bad:
    frozen = pin.get("official_base", {}).get("frozen", {})
    print("pin check: official side frozen at %s (%s), %d files match"
          % (frozen.get("head", base[:12]), branch, len(base_map)),
          file=sys.stderr)
    sys.exit(0)

print("pin check: %s (%s) carries content the corpus was not imported from."
      % (head, branch), file=sys.stderr)
for rel, expected, actual in bad:
    print("  %s" % rel, file=sys.stderr)
    print("    official_base %s" % expected[:16], file=sys.stderr)
    print("    in this tree  %s" % (actual[:16] if actual != "missing" else "missing"),
          file=sys.stderr)
    if has_git and actual != "missing":
        log = git("log", "--oneline", "--format=%h %an | %s",
                  "%s..HEAD" % base, "--", rel).stdout.strip()
        for line in log.splitlines():
            print("    changed by     %s" % line, file=sys.stderr)
print("The official side is frozen in PIN.json `official_base` (see "
      "ab/docs/OFFICIAL-BASE.md). Changing one of these files is a baseline "
      "change: rebuild, re-run every direction of evidence, and update the map "
      "in the same commit.", file=sys.stderr)
sys.exit(1)
PY
