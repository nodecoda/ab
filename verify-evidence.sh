#!/usr/bin/env bash
set -euo pipefail

# verify-evidence.sh [DIRECTION]
#
# Re-check the recorded A/B evidence: every artifact still hashes to what
# EVIDENCE.json says, every diff still reports the recorded summary, and every
# negative control still attributes all of its disagreements to the rulesets it
# injected.
#
#   DIRECTION   G | G-neg | U | U-neg | D | MIR   (default: all)
#
# VERIFY_FROZEN=1 ignores the live /tmp artifacts and reads only the committed
# copies under oracle/.  That is what CI uses: it proves the repo alone can
# replay the evidence, without the build tree or the original run directories.
#
# The artifacts themselves live under /tmp and are not committed.  A missing
# artifact is a failure, not a skip: the manifest records the command that
# regenerates it.  Exit 1 on the first failing entry (after reporting all).
#
# Entries that carry a `snapshot` also pin their source: the `.gisel` corpus,
# the feature file, and the generated `inc`.  The inc is regenerated from the
# corpus during verification, so an answer set cannot stay "green" after the
# corpus or the generator moved underneath it.

HERE=$(cd "$(dirname "$0")" && pwd)
MANIFEST=${VERIFY_MANIFEST:-$HERE/EVIDENCE.json}
export AB_HOME=$HERE
exec python3 - "$MANIFEST" "${1:-all}" "${VERIFY_FROZEN:-0}" <<'PY'
import gzip
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile

manifest_path, want, frozen = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
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
    if not frozen:
        if path is not None:
            candidates.append(pathlib.Path(path))
        candidates.append(d / name)
        candidates.append(d / (name + ".gz"))
    frozen_dir = oracle_root / entry["id"]
    candidates.append(frozen_dir / name)
    candidates.append(frozen_dir / (name + ".gz"))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None

def read(path):
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data

def ok(entry):
    where = oracle_root / entry["id"] if frozen or not pathlib.Path(entry["dir"]).exists() \
        else pathlib.Path(entry["dir"])
    print("PASS %-16s %s" % (entry["id"], where))


def check_mir(entry, expect):
    """A MIR replay report: bucket totals, per-target buckets, and a clean restore.

    The report carries `generated_at`, so its sha256 only ever matches the run
    that wrote it; the numbers are what a reader should trust, and the
    provenance file is what says the tree went back to baseline afterwards.
    """
    bad = 0
    path = resolve(entry, entry.get("report", "mir-report.json"))
    if path is None:
        return fail(entry, "missing mir-report.json")
    report = json.loads(read(path).decode())
    totals = report.get("totals") or {}
    for key, value in (expect.get("mir") or {}).items():
        if totals.get(key) != value:
            bad += fail(entry, "totals %s=%r, expected %r"
                        % (key, totals.get(key), value))
    for target, want in (expect.get("mir_targets") or {}).items():
        got = (report.get("targets") or {}).get(target) or {}
        for key, value in want.items():
            if got.get(key) != value:
                bad += fail(entry, "%s %s=%r, expected %r"
                            % (target, key, got.get(key), value))
    llc = expect.get("llc_sha256")
    if llc and report.get("llc_sha256") != llc:
        bad += fail(entry, "llc sha256 %s, expected %s"
                    % ((report.get("llc_sha256") or "")[:16], llc[:16]))
    prov = resolve(entry, "provenance.json")
    if prov is not None:
        prov = json.loads(read(prov).decode())
        for target, data in (prov.get("targets") or {}).items():
            if data.get("baseline_lib_restored_exactly") is not True:
                bad += fail(entry, "%s baseline library not restored" % target)
    return bad


def per_test(path):
    got = {}
    for line in read(path).decode().splitlines():
        row = json.loads(line)
        got[row["test"]] = (row["status"], row["expected"])
    return got


def per_test_counts(tests):
    got = {"tests": len(tests), "passed": 0, "xfail": 0, "failed": 0,
           "xpass": 0, "unsupported": 0, "aborted": 0}
    for status, expected in tests.values():
        if status == "PASS":
            got["passed" if expected else "xpass"] += 1
        elif status == "FAIL":
            got["xfail" if expected else "failed"] += 1
        elif status == "SKIP":
            got["unsupported"] += 1
        else:
            got["aborted"] += 1
    return got


def check_lit(entry, expect):
    """A whole check-llvm round pair, re-derived from the per-test records.

    `l3.py compare` leaves one line per test per round; this recomputes the
    comparison instead of trusting summary["identical"].  The provenance must
    also say the three libraries were different while the .inc was in place
    and came back to the baseline bytes afterwards: a green summary is also
    what two runs against the same build would produce.
    """
    bad = 0
    summary_path = resolve(entry, entry.get("summary", "l3-summary.json"))
    if summary_path is None:
        return fail(entry, "missing l3-summary.json")
    summary = json.loads(read(summary_path).decode())
    want = expect.get("lit") or {}
    for side in ("baseline", "combined"):
        got = summary.get(side) or {}
        for key, value in (want.get(side) or {}).items():
            if got.get(key) != value:
                bad += fail(entry, "%s %s=%r, expected %r"
                            % (side, key, got.get(key), value))
        got = summary.get("log.%s" % side) or {}
        for key, value in (want.get("log.%s" % side) or {}).items():
            if got.get(key) != value:
                bad += fail(entry, "log.%s %s=%r, expected %r"
                            % (side, key, got.get(key), value))
    for key in ("tests_compared", "identical"):
        if key in want and summary.get(key) != want[key]:
            bad += fail(entry, "%s=%r, expected %r"
                        % (key, summary.get(key), want[key]))

    sides = {}
    for side in ("baseline", "combined"):
        path = resolve(entry, "l3-%s.tests.jsonl" % side)
        if path is None:
            bad += fail(entry, "missing l3-%s.tests.jsonl" % side)
            continue
        sides[side] = per_test(path)
        got = per_test_counts(sides[side])
        for key, value in (want.get(side) or {}).items():
            if got.get(key) != value:
                bad += fail(entry, "%s recomputed %s=%r, expected %r"
                            % (side, key, got.get(key), value))
    if len(sides) == 2:
        base, swap = sides["baseline"], sides["combined"]
        extra = set(base) - set(swap)
        missing = set(swap) - set(base)
        changed = [name for name in set(base) & set(swap)
                   if base[name] != swap[name]]
        if extra:
            bad += fail(entry, "%d tests only in baseline (first: %s)"
                        % (len(extra), sorted(extra)[0]))
        if missing:
            bad += fail(entry, "%d tests only in combined (first: %s)"
                        % (len(missing), sorted(missing)[0]))
        if changed:
            bad += fail(entry, "%d tests changed result (first: %s %r -> %r)"
                        % (len(changed), sorted(changed)[0],
                           base[sorted(changed)[0]], swap[sorted(changed)[0]]))
        if len(set(base) & set(swap)) != want.get("tests_compared"):
            bad += fail(entry, "tests_compared recomputes to %d"
                        % len(set(base) & set(swap)))

    prov_path = resolve(entry, "l3-provenance.json")
    if prov_path is None:
        return bad + fail(entry, "missing l3-provenance.json")
    prov = json.loads(read(prov_path).decode())
    if prov.get("tree_clean_after") is not True:
        bad += fail(entry, "tree was not clean after the restore")
    libs = prov.get("libs") or {}
    for target, restored in (libs.get("restored_exactly") or {}).items():
        if restored is not True:
            bad += fail(entry, "%s library did not come back to baseline bytes"
                        % target)
    for target in (libs.get("baseline") or {}):
        if (libs.get("swapped") or {}).get(target) == libs["baseline"][target]:
            bad += fail(entry, "%s library was identical after the .inc swap: "
                               "the combined round tested nothing" % target)
    return bad


def gisel_root():
    env = os.environ.get("GISEL_SRC")
    if env:
        return pathlib.Path(env)
    home = pathlib.Path(os.environ.get("AB_HOME", manifest_path)).resolve()
    if home.name == "EVIDENCE.json":
        home = home.parent
    return home.parent / "gisel"


def check_snapshot(entry):
    """The corpus -> inc -> answers chain a G/U entry belongs to.

    A recorded answer set is only evidence for the `.gisel` file and the
    `inc` that produced it.  Hash both, then regenerate the inc from the
    corpus so the committed artifact cannot drift away from its source while
    the hashes stay pinned.
    """
    snap = entry.get("snapshot")
    if not snap:
        return 0
    root = gisel_root()
    bad = 0
    for label, rel, key in (
            ("corpus", "tests/corpus/" + snap["corpus"], "corpus_sha256"),
            ("features", "tests/cases/" + snap["features"], "features_sha256")):
        path = root / rel
        if not path.exists():
            bad += fail(entry, "snapshot %s missing: %s" % (label, path))
            continue
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != snap[key]:
            bad += fail(entry, "snapshot %s sha256 %s != %s"
                        % (label, got[:16], snap[key][:16]))
    inc = root / "tests" / "artifacts" / snap["inc"]
    if not inc.exists():
        bad += fail(entry, "snapshot inc missing: %s" % inc)
    else:
        got = hashlib.sha256(inc.read_bytes()).hexdigest()
        if got != snap["inc_sha256"]:
            bad += fail(entry, "snapshot inc sha256 %s != %s"
                        % (got[:16], snap["inc_sha256"][:16]))
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "regen.inc"
        proc = subprocess.run(
            [sys.executable, "-m", "gisel", "gen",
             str(root / "tests" / "corpus" / snap["corpus"]),
             "--emit=inc", "--out", str(out)],
            cwd=str(root), capture_output=True, text=True)
        if proc.returncode:
            bad += fail(entry, "snapshot regen failed: %s"
                        % (proc.stderr.strip().splitlines()[-1:] or [""])[0])
        else:
            got = hashlib.sha256(out.read_bytes()).hexdigest()
            if got != snap["inc_sha256"]:
                bad += fail(entry, "snapshot regen sha256 %s != %s"
                            % (got[:16], snap["inc_sha256"][:16]))
    return bad


def check(entry):
    d = pathlib.Path(entry["dir"])
    bad = 0
    bad += check_snapshot(entry)

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
    if entry.get("kind") == "mir":
        bad += check_mir(entry, expect)
        if not bad:
            ok(entry)
        return bad

    if entry.get("kind") == "lit":
        bad += check_lit(entry, expect)
        if not bad:
            ok(entry)
        return bad

    if entry.get("kind") == "summary":
        # A per-config domain run has one diff per config, not one file.  The
        # aggregate it does have is summary.json, checked below.
        diff = {}
    else:
        diff_path = resolve(entry, entry.get("diff", "diff.json"))
        if diff_path is None:
            return bad + fail(entry, "missing %s"
                              % entry.get("diff", "diff.json"))
        diff = json.loads(read(diff_path).decode())

    if expect.get("answers_identical"):
        pa = resolve(entry, "official.answers.jsonl")
        pb = resolve(entry, "ours.answers.jsonl")
        if pa is None or pb is None:
            return bad + fail(entry, "missing answer files")
        a = read(pa)
        b = read(pb)
        if a != b:
            bad += fail(entry, "answer files differ (diff.json alone is not enough)")

    for key in ("ref", "agree", "disagree", "unanswerable", "ref_asserted"):
        if key in expect and diff.get(key) != expect[key]:
            bad += fail(entry, "%s=%r, expected %r" % (key, diff.get(key), expect[key]))

    by_site = expect.get("ref_asserted_by_site")
    if by_site is not None and diff.get("ref_asserted_by_site") != by_site:
        bad += fail(entry, "ref_asserted_by_site=%r, expected %r"
                    % (diff.get("ref_asserted_by_site"), by_site))

    sites_expect = expect.get("assert_sites")
    if sites_expect:
        sites_path = resolve(entry, entry.get("sites", "sites.json"))
        if sites_path is None:
            bad += fail(entry, "missing assert-site summary")
        else:
            sites = json.loads(read(sites_path).decode()).get("assert_sites", {})
            for key, value in sites_expect.items():
                if sites.get(key) != value:
                    bad += fail(entry, "assert_sites %s=%r, expected %r"
                                % (key, sites.get(key), value))

    summary_expect = expect.get("summary")
    if summary_expect:
        path = resolve(entry, "summary.json")
        if path is None:
            return bad + fail(entry, "missing summary.json")
        summary = json.loads(read(path).decode())
        for key, value in summary_expect.items():
            if summary.get(key) != value:
                bad += fail(entry, "summary %s=%r, expected %r"
                            % (key, summary.get(key), value))

    minimum = expect.get("min_disagree")
    if minimum is not None:
        if diff.get("disagree", 0) < minimum:
            bad += fail(entry, "disagree=%r, expected >= %d"
                        % (diff.get("disagree"), minimum))
        path = resolve(entry, "attribution.json")
        if path is None:
            return bad + fail(entry, "missing attribution.json")
        attribution = json.loads(read(path).decode())
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
        ok(entry)
    return bad

def check_build(manifest):
    """The evidence belongs to one build.  A rebuilt library invalidates it."""
    build = manifest.get("official_build")
    if not build:
        return 0
    root = pathlib.Path(build["path"])
    if not root.exists():
        print("SKIP official_build  %s is not present" % root)
        return 0
    bad = 0
    for target, want in sorted(build["libs"].items()):
        lib = root / "lib" / ("libLLVM%sCodeGen.so.24.0git" % target)
        if not lib.exists():
            print("FAIL official_build  missing %s" % lib)
            bad += 1
            continue
        got = hashlib.sha256(lib.read_bytes()).hexdigest()
        if got != want:
            print("FAIL official_build  %s is %s, evidence was recorded against %s"
                  % (lib.name, got[:16], want[:16]))
            bad += 1
    if not bad:
        print("PASS official_build  %s (%d libraries)" % (root, len(build["libs"])))
    return bad


build_failures = check_build(manifest)

total = failures = 0
for entry in manifest["entries"]:
    if want != "all" and entry["direction"] != want:
        continue
    total += 1
    failures += check(entry)

print("%d/%d entries pass" % (total - failures, total))
if any((want == "all" or e["direction"] == want)
       and e["id"].startswith("U-full/") for e in manifest["entries"]):
    # O8: say it out loud so a reader does not think the expanded query file
    # was silently dropped.
    print("NOTE U-full/*: only `universe.jsonl` and the expand command are "
          "frozen; the 144-473 MB expanded query file is regenerated on "
          "demand (docs/EVIDENCE-U.md).")
sys.exit(1 if (failures or build_failures) else 0)
PY
