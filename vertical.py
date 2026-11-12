#!/usr/bin/env python3
"""Run or verify one target's vertical slice.

    python3 vertical.py --target x86 --tree TREE --build BUILD --out OUT [--l3]
    python3 vertical.py --target x86 --out OUT --verify-only [--frozen]
    python3 vertical.py --target x86 --out OUT --record

The slice is: gisel cases -> G A/B; oracle U queries -> U A/B; negative
controls for both directions; the full domain; MIR L1 (upstream MIR) and L2
(queries -> MIR); optionally L3 (single-target check-llvm).

Every step is checked against data/<target>-contract.json.  The contract pins
the inc, the query files, the counts and the answers, so a green run means
"the current gisel output still produces the recorded evidence".

`--record` runs the slice and writes the contract from the artifacts it just
produced.  It is for adding a target, not for refreshing one: the diff of the
contract is the review material.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GISEL = Path(__file__).resolve().parent.parent / "gisel"
DEFAULT_TREE = Path("/home/ubuntu/llvm/trees/explore")
DEFAULT_BUILD = Path("/home/ubuntu/llvm/builds/explore")

sys.path.insert(0, str(ROOT))
import targets as target_registry  # noqa: E402


def spec_from(doc: dict) -> dict:
    """The view vertical.py needs, derived from targets/<name>.json."""
    return {
        "contract": doc["contract"],
        "inc": doc["artifact"],
        "corpus": Path(doc["source"]).name,
        "features": Path(doc["features"]).name,
        "end_to_end": doc["e2e"],
        "domain": doc["domain"],
        "g_neg": doc["g_neg"],
        "u_neg": doc["u_neg"],
        "u_prefix": doc["u_prefix"],
        "allow_unanswerable": str(doc["allow_unanswerable"]),
    }


def contract_targets() -> dict:
    out = {}
    for name in target_registry.names():
        doc = target_registry.load(name)
        if doc["contract"]:
            out[name] = spec_from(doc)
    return out


# A derived view, not a registry: only targets with a recorded contract can
# run this slice.  Nine-target frozen replay is replay-frozen.py.
TARGETS = contract_targets()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text())



def contract_pin(value, contract, section, key):
    """An explicit flag wins; otherwise reuse the number the contract pinned."""
    if value is not None:
        return value
    if contract is None:
        return None
    return contract.get(section, {}).get(key)


def pins(timeouts, unsupported):
    """`mir-replay` flags for the two uncompared buckets, when they are known."""
    args = []
    if timeouts is not None:
        args += ["--expect-timeouts", str(timeouts)]
    if unsupported is not None:
        args += ["--expect-unsupported", str(unsupported)]
    return args


def leg_command(script, target, *args, tree, build):
    """A U / G-negative leg command with its provenance made explicit.

    These legs used to rely on `AB_TREE`/`AB_BUILD` defaults while the contract
    recorded the `--tree` given to the G leg, so the evidence could name one
    build and use another.  There is exactly one constructor now.
    """
    return [ROOT / script, target, *(str(a) for a in args),
            "--tree", str(tree), "--build", str(build)]


def run_cmd(cmd, cwd=None, log=None, check=True):
    text = " ".join(str(x) for x in cmd)
    print("+ " + text, flush=True)
    kwargs = {"cwd": str(cwd) if cwd else None}
    if log is not None:
        with open(log, "w") as fh:
            proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                  **kwargs)
    else:
        proc = subprocess.run(cmd, **kwargs)
    if check and proc.returncode:
        raise SystemExit("command failed (%d): %s" % (proc.returncode, text))
    return proc.returncode


def _frozen_bytes(parts) -> bytes:
    path = ROOT.joinpath(*parts)
    if not path.exists():
        path = path.with_name(path.name + ".gz")
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def frozen_files(target: str) -> dict:
    """The artifact layout `--verify-only` reads, and its frozen source."""
    return {
        "g/queries.jsonl": ("oracle", "G/%s" % target, "queries.jsonl"),
        "g/diff.json": ("oracle", "G/%s" % target, "diff.json"),
        "g/official.answers.jsonl": ("oracle", "G/%s" % target,
                                     "official.answers.jsonl"),
        "g/ours.answers.jsonl": ("oracle", "G/%s" % target,
                                 "ours.answers.jsonl"),
        "u/queries.jsonl": ("oracle", "U/%s" % target, "queries.jsonl"),
        "u/diff.json": ("oracle", "U/%s" % target, "diff.json"),
        "u/official.answers.jsonl": ("oracle", "U/%s" % target,
                                     "official.answers.jsonl"),
        "u/ours.answers.jsonl": ("oracle", "U/%s" % target,
                                 "ours.answers.jsonl"),
        "u/attribution.json": ("oracle", "U/%s" % target, "attribution.json"),
        "u-neg/diff.json": ("oracle", "U-neg/%s" % target, "diff.json"),
        "u-neg/attribution.json": ("oracle", "U-neg/%s" % target,
                                   "attribution.json"),
        "g-neg/run/diff.json": ("oracle", "G-neg/%s" % target, "diff.json"),
        "g-neg/run/attribution.json": ("oracle", "G-neg/%s" % target,
                                       "attribution.json"),
        "domain/summary.json": ("oracle", "%s-vertical" % target,
                                "domain-summary.json"),
        "l1/mir-report.json": ("oracle", "%s-vertical/l1" % target,
                               "mir-report.json"),
        "l2/replay/mir-report.json": ("oracle", "%s-vertical/l2" % target,
                                      "mir-report.json"),
    }


def materialize_frozen(target: str) -> Path:
    """Rebuild the artifact layout from the frozen copies under `oracle/`.

    `--verify-only` is otherwise tied to a /tmp directory that CI does not
    have.  Everything the verifier reads is committed, so a clean checkout can
    re-check a slice without the build tree or the network.
    """
    out = Path(tempfile.mkdtemp(prefix="%s-vertical-" % target))
    for rel, parts in frozen_files(target).items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_frozen_bytes(parts))
    return out


def fail(failures, message):
    failures.append(message)


def check(failures, cond, message):
    if not cond:
        fail(failures, message)


def check_sha(failures, path: Path, want: str, label: str):
    if not path.exists():
        fail(failures, "%s: missing %s" % (label, path))
        return None
    got = sha256(path)
    check(failures, got == want, "%s: sha256 %s, expected %s"
          % (label, got[:16], want[:16]))
    return got


def require_sha(path: Path, want: str, label: str):
    got = sha256(path)
    if got != want:
        raise SystemExit("%s: sha256 %s, expected %s (%s)"
                         % (label, got, want, path))


def verify_g(out: Path, c, failures):
    g = c["g"]
    d = load(out / "g" / "diff.json")
    for key in ("ref", "ours", "matched"):
        check(failures, d.get(key) == g["queries"],
              "G: %s=%r, expected %r" % (key, d.get(key), g["queries"]))
    for key in ("agree", "disagree", "unanswerable", "missing_ref",
                "missing_ours", "errors"):
        want = g[key] if key in g else 0
        check(failures, d.get(key) == want,
              "G: %s=%r, expected %r" % (key, d.get(key), want))
    check_sha(failures, out / "g" / "queries.jsonl",
              g["queries_sha256"], "G queries")
    official = sha256(out / "g" / "official.answers.jsonl")
    ours = sha256(out / "g" / "ours.answers.jsonl")
    check(failures, official == ours, "G: answer files differ")
    check(failures, official == g["answers_sha256"],
          "G: answers sha256 %s, expected %s"
          % (official[:16], g["answers_sha256"][:16]))
    # diff.json is a derived view: newer harness versions add fields (for
    # example assert_sites) without changing a count.  The verdict is pinned
    # by the counts above and by the answer files; the bytes are not.
    if g.get("diff_sha256"):
        check_sha(failures, out / "g" / "diff.json", g["diff_sha256"],
                  "G diff")


def verify_u(out: Path, c, failures, u_queries: Path):
    u = c["u"]
    d = load(out / "u" / "diff.json")
    for key in ("ref", "ours", "matched"):
        check(failures, d.get(key) == u["queries"],
              "U: %s=%r, expected %r" % (key, d.get(key), u["queries"]))
    for key in ("agree", "disagree", "unanswerable", "missing_ref",
                "missing_ours", "errors"):
        want = u[key] if key in u else 0
        check(failures, d.get(key) == want,
              "U: %s=%r, expected %r" % (key, d.get(key), want))
    qpath = out / "u" / "queries.jsonl"
    if not qpath.exists():
        qpath = u_queries
    check_sha(failures, qpath, u["queries_sha256"], "U queries")
    official = sha256(out / "u" / "official.answers.jsonl")
    ours = sha256(out / "u" / "ours.answers.jsonl")
    check(failures, official == ours, "U: answer files differ")
    check(failures, official == u["answers_sha256"],
          "U: answers sha256 %s, expected %s"
          % (official[:16], u["answers_sha256"][:16]))
    if u.get("diff_sha256"):
        check_sha(failures, out / "u" / "diff.json", u["diff_sha256"], "U diff")
    a = load(out / "u" / "attribution.json")
    check(failures, a.get("disagree") == 0, "U attribution: disagree != 0")
    check(failures, a.get("unknown_keys") == 0,
          "U attribution: unknown_keys != 0")
    check_sha(failures, out / "u" / "attribution.json",
              u["attribution_sha256"], "U attribution")


def verify_neg(out: Path, c, failures, label, subdir, attribution_name):
    spec = c[label]
    path = out / subdir / attribution_name
    a = load(path)
    check(failures, a.get("disagree") == spec["disagree"],
          "%s: disagree=%r, expected %r"
          % (label, a.get("disagree"), spec["disagree"]))
    check(failures, a.get("by_ruleset") == spec["rulesets"],
          "%s: by_ruleset=%r, expected %r"
          % (label, a.get("by_ruleset"), spec["rulesets"]))
    check(failures, a.get("unknown_keys") == spec["unknown_keys"],
          "%s: unknown_keys=%r" % (label, a.get("unknown_keys")))
    check(failures, not a.get("outside_expected"),
          "%s: outside_expected is not empty" % label)
    check_sha(failures, path, spec["attribution_sha256"], label + " attribution")


def verify_domain(out: Path, c, failures):
    d = c["domain"]
    s = load(out / "domain" / "summary.json")
    check(failures, s.get("configs") == d["configs"],
          "domain: configs=%r" % s.get("configs"))
    for key in ("queries", "agree", "disagree", "unanswerable"):
        check(failures, s.get(key) == d[key],
              "domain: %s=%r, expected %r" % (key, s.get(key), d[key]))
    for row in s.get("per_config", []):
        cfg = row.get("config")
        check(failures, row.get("ref") == d["per_config"],
              "domain/%s: ref=%r" % (cfg, row.get("ref")))
        check(failures, row.get("disagree") == 0,
              "domain/%s: disagree=%r" % (cfg, row.get("disagree")))
        if d.get("unanswerable_map"):
            check(failures,
                  row.get("unanswerable") == d["unanswerable_map"].get(cfg),
                  "domain/%s: unanswerable=%r, expected %r"
                  % (cfg, row.get("unanswerable"),
                     d["unanswerable_map"].get(cfg)))
    check_sha(failures, out / "domain" / "summary.json",
              d["summary_sha256"], "domain summary")


def verify_mir(out: Path, c, failures):
    l1 = load(out / "l1" / "mir-report.json").get("totals", {})
    for key, want in c["mir_l1"].items():
        check(failures, l1.get(key) == want,
              "L1: %s=%r, expected %r" % (key, l1.get(key), want))
    l2path = out / "l2" / "replay" / "mir-report.json"
    if not l2path.exists():
        l2path = out / "l2" / "mir-report.json"
    l2 = load(l2path).get("totals", {})
    for key, want in c["mir_l2"].items():
        check(failures, l2.get(key) == want,
              "L2: %s=%r, expected %r" % (key, l2.get(key), want))


def parse_l3(path: Path):
    text = path.read_text()
    def grab(label, default=0):
        m = re.search(r"^\s*" + label + r"\s*:\s*([\d,]+)", text, re.M)
        return int(m.group(1).replace(",", "")) if m else default
    return {
        "discovered": grab(r"Total Discovered Tests"),
        "passed": grab(r"Passed"),
        "xfail": grab(r"Expectedly Failed"),
        "failed": grab(r"Failed"),
    }


def verify_l3(out: Path, c, failures, required):
    path = out / "l3.log"
    if not path.exists():
        if required:
            fail(failures, "L3: %s missing" % path)
        return None
    got = parse_l3(path)
    for key, want in c["l3"].items():
        check(failures, got[key] == want,
              "L3: %s=%r, expected %r" % (key, got[key], want))
    return got


def verify(out: Path, c, u_queries: Path, target: str, contract: Path,
           l3_required=False):
    failures = []
    check_sha(failures, out / "g" / "queries.jsonl",
              c["g"]["queries_sha256"], "G queries (snapshot)")
    verify_g(out, c, failures)
    verify_u(out, c, failures, u_queries)
    verify_neg(out, c, failures, "u_neg", "u-neg", "attribution.json")
    verify_neg(out, c, failures, "g_neg", "g-neg/run", "attribution.json")
    verify_domain(out, c, failures)
    verify_mir(out, c, failures)
    l3 = verify_l3(out, c, failures, l3_required)
    if failures:
        print("\nFAIL (%d)" % len(failures), file=sys.stderr)
        for item in failures:
            print("  - " + item, file=sys.stderr)
        return 1
    u_qpath = out / "u" / "queries.jsonl"
    if not u_qpath.exists():
        u_qpath = u_queries
    manifest = {
        "schema": 1,
        "target": target,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "out": str(out),
        "contract": str(contract),
        "snapshot": c["snapshot"],
        "l3": l3,
        "artifacts": {
            "inc": c["snapshot"]["inc_sha256"],
            "g_queries": sha256(out / "g" / "queries.jsonl"),
            "g_answers": sha256(out / "g" / "official.answers.jsonl"),
            "u_queries": sha256(u_qpath),
            "u_answers": sha256(out / "u" / "official.answers.jsonl"),
            "domain_summary": sha256(out / "domain" / "summary.json"),
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("\nPASS: %s vertical slice matches %s" % (target, contract))
    return 0


def _git_head(path: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _pin_line() -> str:
    try:
        doc = load(ROOT.parent / "upstream-source" / "pin" / "PIN.json")
    except OSError:
        return "unknown"
    patches = doc.get("patches") or []
    return "%s + %d patches" % (doc.get("commit", "unknown"), len(patches))


def build_contract(target: str, out: Path, u_queries: Path, tree: Path) -> dict:
    """The contract a `--record` run just earned."""
    g = load(out / "g" / "diff.json")
    u = load(out / "u" / "diff.json")
    u_att = load(out / "u" / "attribution.json")
    u_neg = load(out / "u-neg" / "attribution.json")
    g_neg = load(out / "g-neg" / "run" / "attribution.json")
    dom = load(out / "domain" / "summary.json")
    l1 = load(out / "l1" / "mir-report.json")["totals"]
    l2 = load(out / "l2" / "replay" / "mir-report.json")["totals"]
    u_qpath = out / "u" / "queries.jsonl"
    if not u_qpath.exists():
        u_qpath = u_queries
    return {
        "schema": 1,
        "target": target,
        "comment": ("Every count and hash here was recorded by "
                    "`vertical.py --target %s --record` at the snapshot "
                    "below; `--verify-only` re-derives the comparison "
                    "instead of trusting the summary." % target),
        "snapshot": {
            "tree_commit": _git_head(tree),
            "gisel_commit": _git_head(GISEL),
            "pin": _pin_line(),
            "inc_sha256": sha256(ROOT.parent / "gisel" / "tests" /
                                 "artifacts" / TARGETS[target]["inc"]),
            "corpus_sha256": sha256(GISEL / "tests" / "corpus" /
                                    TARGETS[target]["corpus"]),
            "features_sha256": sha256(GISEL / "tests" / "cases" /
                                      TARGETS[target]["features"]),
        },
        "g": {
            "queries": g["matched"],
            "queries_sha256": sha256(out / "g" / "queries.jsonl"),
            "agree": g.get("agree", 0),
            "disagree": g.get("disagree", 0),
            "unanswerable": g.get("unanswerable", 0),
            "missing_ref": g.get("missing_ref", 0),
            "missing_ours": g.get("missing_ours", 0),
            "errors": g.get("errors", 0),
            "answers_sha256": sha256(out / "g" / "official.answers.jsonl"),
        },
        "u": {
            "queries": u["matched"],
            "queries_sha256": sha256(u_qpath),
            "agree": u.get("agree", 0),
            "disagree": u.get("disagree", 0),
            "unanswerable": u.get("unanswerable", 0),
            "missing_ref": u.get("missing_ref", 0),
            "missing_ours": u.get("missing_ours", 0),
            "errors": u.get("errors", 0),
            "answers_sha256": sha256(out / "u" / "official.answers.jsonl"),
            "attribution_sha256": sha256(out / "u" / "attribution.json"),
        },
        "u_neg": {
            "opcode": TARGETS[target]["u_neg"],
            "disagree": u_neg["disagree"],
            "rulesets": u_neg["by_ruleset"],
            "unknown_keys": u_neg["unknown_keys"],
            "attribution_sha256": sha256(out / "u-neg" /
                                         "attribution.json"),
        },
        "g_neg": {
            "opcode": TARGETS[target]["g_neg"],
            "disagree": g_neg["disagree"],
            "rulesets": g_neg["by_ruleset"],
            "unknown_keys": g_neg["unknown_keys"],
            "attribution_sha256": sha256(out / "g-neg" / "run" /
                                         "attribution.json"),
        },
        "domain": {
            "configs": dom["configs"],
            "per_config": (max(row["ref"] for row in dom["per_config"])
                           if dom.get("per_config") else None),
            "queries": dom["queries"],
            "agree": dom["agree"],
            "disagree": dom["disagree"],
            "unanswerable": dom["unanswerable"],
            "unanswerable_map": {row["config"]: row["unanswerable"]
                                 for row in dom.get("per_config", [])},
            "summary_sha256": sha256(out / "domain" / "summary.json"),
        },
        "mir_l1": l1,
        "mir_l2": l2,
        "l3": {
            "discovered": 0, "passed": 0, "xfail": 0, "failed": 0,
        },
    }


def main(argv=None, default_target="riscv"):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default=default_target)
    ap.add_argument("--tree", default=str(DEFAULT_TREE))
    ap.add_argument("--build", default=str(DEFAULT_BUILD))
    ap.add_argument("--out", required=True)
    ap.add_argument("--u-queries", default=None)
    ap.add_argument("--l3", action="store_true",
                    help="also run a single-target check-llvm round")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--frozen", action="store_true",
                    help="with --verify-only: rebuild the layout from ./oracle")
    ap.add_argument("--record", action="store_true",
                    help="write data/<target>-contract.json from this run")
    ap.add_argument("--expect-l1-timeouts", type=int, default=None, metavar="N")
    ap.add_argument("--expect-l1-unsupported", type=int, default=None,
                    metavar="N")
    ap.add_argument("--expect-l2-timeouts", type=int, default=None, metavar="N")
    ap.add_argument("--expect-l2-unsupported", type=int, default=None,
                    metavar="N")
    args = ap.parse_args(argv)

    if args.target not in TARGETS:
        raise SystemExit(
            "%s: no vertical contract; this script needs data/%s-contract.json "
            "(nine-target frozen replay is replay-frozen.py)"
            % (args.target, args.target))
    spec = TARGETS[args.target]
    out = Path(args.out).resolve()
    tree = Path(args.tree).resolve()
    build = Path(args.build).resolve()
    contract = ROOT / spec["contract"]
    inc = GISEL / "tests" / "artifacts" / spec["inc"]
    u_queries = Path(args.u_queries) if args.u_queries else Path(
        "/tmp/u-gen/%s/queries.jsonl" % spec["u_prefix"])
    u_queries = u_queries.resolve()

    if args.verify_only:
        if args.frozen:
            out = materialize_frozen(args.target)
        if not contract.exists():
            raise SystemExit("no contract: %s" % contract)
        return verify(out, load(contract), u_queries, args.target, contract,
                      l3_required=args.l3)

    if contract.exists() and not args.record:
        c = load(contract)
        require_sha(inc, c["snapshot"]["inc_sha256"], "inc")
        require_sha(GISEL / "tests" / "corpus" / spec["corpus"],
                    c["snapshot"]["corpus_sha256"], "corpus")
        require_sha(GISEL / "tests" / "cases" / spec["features"],
                    c["snapshot"]["features_sha256"], "features")
    else:
        c = None

    out.mkdir(parents=True, exist_ok=True)
    if not u_queries.exists():
        raise SystemExit(
            "U queries missing: %s\nGenerate them with:\n"
            "  cd /home/ubuntu/llvm/upstream-source\n"
            "  ./oracle/scripts/gen-u.sh %s /tmp/u-gen/%s"
            % (u_queries, args.target, spec["u_prefix"]))

    run_cmd([ROOT / spec["end_to_end"], tree, build, inc, out / "g"])
    run_cmd(leg_command("run-u-end-to-end.sh", args.target, u_queries,
                        out / "u", "--allow-unanswerable",
                        spec["allow_unanswerable"], tree=tree, build=build))
    dest = out / "u" / "queries.jsonl"
    if dest.resolve() != u_queries.resolve():
        dest.write_bytes(u_queries.read_bytes())
    run_cmd(leg_command("run-u-end-to-end.sh", args.target, u_queries,
                        out / "u-neg", "--drop-opcode", spec["u_neg"],
                        tree=tree, build=build))
    run_cmd(leg_command("run-g-negative.sh", args.target, spec["g_neg"],
                        out / "g-neg", tree=tree, build=build))
    run_cmd([ROOT / spec["domain"], tree, build, inc, out / "domain"])

    l1_timeouts = contract_pin(args.expect_l1_timeouts, c, "mir_l1",
                               "timeout")
    l1_unsupported = contract_pin(args.expect_l1_unsupported, c, "mir_l1",
                                  "unsupported_run")
    l2_timeouts = contract_pin(args.expect_l2_timeouts, c, "mir_l2",
                               "timeout")
    l2_unsupported = contract_pin(args.expect_l2_unsupported, c, "mir_l2",
                                  "unsupported_run")

    run_cmd([sys.executable, ROOT / "mir-replay.py", "--layer", "upstream",
             "--target", args.target, "--tree", tree, "--build", build,
             "--out", out / "l1", "--prepare", "--json",
             *pins(l1_timeouts, l1_unsupported)])

    run_cmd([sys.executable, ROOT / "ab.py", "mir", "--target", args.target,
             "--queries", out / "g" / "queries.jsonl", "--tree", tree,
             "--build", build, "--out", out / "l2", "--json",
             *pins(l2_timeouts, l2_unsupported)])

    if args.l3:
        apply = [sys.executable, ROOT / "swap-source-ctor.py", "apply",
                 "--target", args.target, "--tree", tree, "--inc", inc]
        restore = [sys.executable, ROOT / "swap-source-ctor.py", "restore",
                   "--target", args.target, "--tree", tree]
        run_cmd(apply)
        rc = 1
        try:
            rc = run_cmd(["ninja", "-j32", "check-llvm"], cwd=build,
                         log=out / "l3.log", check=False)
        finally:
            run_cmd(restore)
            run_cmd(["ninja", "-j32"], cwd=build,
                    log=out / "l3-restore.log", check=False)
        if rc:
            raise SystemExit("check-llvm failed (rc=%d); see %s"
                             % (rc, out / "l3.log"))

    if c is None:
        c = build_contract(args.target, out, u_queries, tree)
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_text(json.dumps(c, indent=2) + "\n")
        print("+ wrote %s" % contract)
    return verify(out, c, u_queries, args.target, contract,
                  l3_required=args.l3)


if __name__ == "__main__":
    sys.exit(main())
