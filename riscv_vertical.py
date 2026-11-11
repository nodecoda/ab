#!/usr/bin/env python3
"""Run or verify the RISC-V vertical slice.

    python3 riscv_vertical.py --tree TREE --build BUILD --out OUT [--l3]
    python3 riscv_vertical.py --out OUT --verify-only

The slice is: gisel cases -> G A/B; oracle U queries -> U A/B; negative
controls for both directions; the full 8-config domain; MIR L1 (upstream
MIR) and L2 (queries -> MIR); optionally L3 (single-target check-llvm).

Every step is checked against data/riscv-contract.json.  The contract pins
the inc, the query files, the counts and the answers, so a green run means
"the current gisel output still produces the recorded RISC-V evidence".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GISEL = Path(__file__).resolve().parent.parent / "gisel"
CONTRACT = ROOT / "data" / "riscv-contract.json"
DEFAULT_TREE = Path("/home/ubuntu/llvm/trees/explore")
DEFAULT_BUILD = Path("/home/ubuntu/llvm/builds/explore")
DEFAULT_U_QUERIES = Path("/tmp/u-gen/rvb/queries.jsonl")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text())


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
    check_sha(failures, out / "g" / "diff.json", g["diff_sha256"], "G diff")


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
        check(failures, row.get("unanswerable") == d["unanswerable_map"].get(cfg),
              "domain/%s: unanswerable=%r, expected %r"
              % (cfg, row.get("unanswerable"), d["unanswerable_map"].get(cfg)))
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


def verify(out: Path, c, u_queries: Path, l3_required=False):
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
        "target": "riscv",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "out": str(out),
        "contract": str(CONTRACT),
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
    print("\nPASS: RISC-V vertical slice matches %s" % CONTRACT)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tree", default=str(DEFAULT_TREE))
    ap.add_argument("--build", default=str(DEFAULT_BUILD))
    ap.add_argument("--out", required=True)
    ap.add_argument("--u-queries", default=str(DEFAULT_U_QUERIES))
    ap.add_argument("--l3", action="store_true",
                    help="also run a single-target check-llvm round")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args(argv)

    out = Path(args.out).resolve()
    c = load(CONTRACT)
    tree = Path(args.tree).resolve()
    build = Path(args.build).resolve()
    inc = GISEL / "tests" / "artifacts" / "riscv.inc"
    u_queries = Path(args.u_queries).resolve()

    if args.verify_only:
        return verify(out, c, u_queries, l3_required=args.l3)

    out.mkdir(parents=True, exist_ok=True)
    require_sha(inc, c["snapshot"]["inc_sha256"], "inc")
    corpus = GISEL / "tests" / "corpus" / "RISCVLegalizerInfo.gisel"
    features = GISEL / "tests" / "cases" / "riscv-features.json"
    require_sha(corpus, c["snapshot"]["corpus_sha256"], "corpus")
    require_sha(features, c["snapshot"]["features_sha256"], "features")

    if not u_queries.exists():
        raise SystemExit(
            "U queries missing: %s\nGenerate them with:\n"
            "  cd /home/ubuntu/llvm/upstream-source\n"
            "  ./oracle/scripts/gen-u.sh riscv /tmp/u-gen/rvb"
            % u_queries)

    run_cmd([ROOT / "run-riscv-end-to-end.sh", tree, build, inc, out / "g"])
    run_cmd([ROOT / "run-u-end-to-end.sh", "riscv", u_queries, out / "u",
             "--allow-unanswerable", "0"])
    target = out / "u" / "queries.jsonl"
    if target.resolve() != u_queries.resolve():
        target.write_bytes(u_queries.read_bytes())
    run_cmd([ROOT / "run-u-end-to-end.sh", "riscv", u_queries,
             out / "u-neg", "--drop-opcode", "G_ADD"])
    run_cmd([ROOT / "run-g-negative.sh", "riscv", "G_FPTOSI", out / "g-neg"])
    run_cmd([ROOT / "run-riscv-domain.sh", tree, build, inc, out / "domain"])

    run_cmd([sys.executable, ROOT / "mir-replay.py", "--layer", "upstream",
             "--target", "riscv", "--tree", tree, "--build", build,
             "--out", out / "l1", "--prepare", "--json"])

    run_cmd([sys.executable, ROOT / "ab.py", "mir", "--target", "riscv",
             "--queries", out / "g" / "queries.jsonl", "--tree", tree,
             "--build", build, "--out", out / "l2", "--json"])

    if args.l3:
        apply = [sys.executable, ROOT / "swap-source-ctor.py", "apply",
                 "--target", "riscv", "--tree", tree, "--inc", inc]
        restore = [sys.executable, ROOT / "swap-source-ctor.py", "restore",
                   "--target", "riscv", "--tree", tree]
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

    return verify(out, c, u_queries, l3_required=args.l3)


if __name__ == "__main__":
    sys.exit(main())
