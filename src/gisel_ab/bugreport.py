"""`gisel-ab bug-report`: one JSON file with the facts a reader would ask for.

    gisel-ab bug-report                 # stdout
    gisel-ab bug-report --out bug.json  # write a file

It collects versions, the cohort record, the doctor verdict and the last
run's ledger line.  It deliberately does not collect the evidence tree: a bug
report is small enough to paste into an issue, and the evidence is fetchable
from the cohort release.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from gisel_ab import doctor

SCHEMA = 1


def _installed(name: str):
    try:
        import importlib.metadata as metadata
        return metadata.version(name)
    except Exception:
        return None


def _module_version(name: str):
    try:
        module = __import__(name)
    except Exception:
        return None
    return getattr(module, "__version__", None)


def _release() -> dict:
    path = doctor.AB_ROOT / "RELEASE.json"
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    keep = ("cohort", "version", "repos", "generated_at")
    return {key: doc[key] for key in keep if key in doc}


def _last_run() -> dict | None:
    ledgers = sorted((doctor.AB_ROOT / ".ab").glob("*/ledger.jsonl"))
    if not ledgers:
        return None
    path = ledgers[-1]
    lines = path.read_text().strip().splitlines()
    if not lines:
        return None
    try:
        record = json.loads(lines[-1])
    except ValueError:
        return {"target": path.parent.name, "ledger": str(path),
                "error": "the last line is not JSON"}
    return {"target": path.parent.name, "ledger": str(path), "record": record}


def report(tree=None, build=None) -> dict:
    from gisel_ab.cli import _version
    checks = doctor.checks(tree, build)
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "versions": {
            "gisel-ab": _version(),
            "gisel-anchor": _module_version("gisel_anchor"),
            "gisel": _module_version("gisel"),
            "installed.gisel-ab": _installed("gisel-ab"),
            "installed.gisel-anchor": _installed("gisel-anchor"),
            "installed.gisel": _installed("gisel"),
        },
        "cohort": _release(),
        "doctor": {"ok": not any(c.status == doctor.FAIL for c in checks),
                   "checks": [c.as_dict() for c in checks]},
        "last_run": _last_run(),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gisel-ab bug-report",
        description="collect versions, the cohort record and the doctor verdict "
                    "into one JSON file (no evidence tree)")
    ap.add_argument("--out", help="write here instead of stdout")
    ap.add_argument("--tree", help="LLVM checkout (default: configured)")
    ap.add_argument("--build", help="ninja build (default: configured)")
    args = ap.parse_args(argv)
    text = json.dumps(report(args.tree, args.build), indent=2,
                      sort_keys=True) + "\n"
    if args.out:
        path = Path(args.out).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print("wrote %s" % path)
        return 0
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
