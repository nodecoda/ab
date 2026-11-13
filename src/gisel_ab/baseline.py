#!/usr/bin/env python3
"""Record the facts a remediation run is measured against.

    baseline.py [--out data/baseline-YYYY-MM-DD.json]

The file is deliberately boring: repository heads, corpus/artifact/feature
hashes, the target registry, and the numbers already pinned by EVIDENCE.json.
It does not run a build and it does not change behavior.  Later waves compare
their output with this snapshot instead of trusting a document's memory.

Exit codes: 0 = written; 2 = a required input is missing or unreadable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from gisel_ab import paths
from gisel_ab import targets as target_specs

PKG = Path(__file__).resolve().parent
AB = PKG.parents[1]
DATA = PKG / "data"
GISEL = Path(__import__("os").environ.get("GISEL_SRC", AB.parent / "gisel"))
UPSTREAM = paths.sibling(AB.parent, "UPSTREAM_SOURCE",
                         "gisel-anchor", "upstream-source")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_state(path: Path) -> dict:
    def git(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit("git %s failed in %s: %s"
                             % (" ".join(args), path, proc.stderr.strip()))
        return proc.stdout.strip()

    return {
        "head": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
    }


def hashes(root: Path, pattern: str) -> dict:
    return {path.relative_to(root).as_posix(): sha256(path)
            for path in sorted(root.glob(pattern)) if path.is_file()}


def evidence_summary(path: Path) -> dict:
    manifest = json.loads(path.read_text())
    entries = {}
    for entry in manifest.get("entries", []):
        expect = entry.get("expect", {})
        entries[entry["id"]] = {
            "direction": entry.get("direction"),
            "target": entry.get("target"),
            "expect": {key: expect[key] for key in sorted(expect)},
            "snapshot": entry.get("snapshot"),
        }
    return {
        "sha256": sha256(path),
        "schema": manifest.get("schema"),
        "generated": manifest.get("generated"),
        "entries": entries,
    }


def target_registry(root: Path) -> dict:
    out = {}
    for path in sorted(target_specs.TARGET_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        out[path.stem] = {
            "sha256": sha256(path),
            "strategy": data.get("strategy"),
            "query_count": data.get("query_count"),
        }
    return out


def build() -> dict:
    for path in (GISEL, UPSTREAM, AB):
        if not path.is_dir():
            raise SystemExit("missing checkout: %s" % path)
    return {
        "snapshot": "pre-remediation",
        "repos": {
            "gisel": repo_state(GISEL),
            "ab": repo_state(AB),
            "upstream-source": repo_state(UPSTREAM),
        },
        "gisel": {
            "corpora": hashes(GISEL, "tests/corpus/*.gisel"),
            "artifacts": hashes(GISEL, "tests/artifacts/*.inc"),
            "features": hashes(GISEL, "tests/cases/*features*.json"),
            "domain_queries": hashes(GISEL, "tests/cases/*domain*.jsonl"),
        },
        "ab": {
            "evidence": evidence_summary(AB / "EVIDENCE.json"),
            "targets": target_registry(AB),
            "contracts": hashes(DATA, "*-contract.json"),
            "gate_scripts": {
                name: sha256(AB / name)
                for name in (
                    "src/gisel_ab/l0/diff.py",
                    "src/gisel_ab/l0/queries.py",
                    "scripts/verify-evidence.sh",
                    "scripts/e2e/run-u-end-to-end.sh",
                    "scripts/negative/run-g-negative.sh",
                    "scripts/negative/run-predicate-negative.sh",
                )
            },
        },
        "upstream_source": {
            "pin_manifest": hashes(UPSTREAM, "pin/*.json"),
            "oracle_queries": hashes(UPSTREAM, "oracle/*/*/queries.jsonl*"),
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="baseline")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    out = args.out or (DATA / ("baseline-%s.json" % date.today()))
    data = build()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
