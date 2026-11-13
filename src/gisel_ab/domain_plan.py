#!/usr/bin/env python3
"""Print the domain plan for one target without building or running anything.

`run-domain.sh TARGET --plan` is the single read-only entry point.  The
numbers stay where they already live:

* generic targets: `data/domain.json` and `targets/<target>.json`;
* x86 / AArch64 / RISC-V: the constants in their own `run-*-domain.sh`
  (they have target-specific build and unanswerable contracts).

Parsing the shell constants is deliberate.  Copying them into a second table
would create exactly the drift this plan is meant to remove.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent
AB_ROOT = PKG.parents[1]
GISEL = Path(os.environ.get("GISEL_SRC",
                            AB_ROOT.parent / "gisel")).resolve()
FEATURES = GISEL / "tests" / "cases"
DOMAIN = PKG / "data" / "domain.json"
TARGETS = PKG / "data" / "targets"
SCRIPTS = AB_ROOT / "scripts"
SPECIAL = {"x86", "aarch64", "riscv"}


def _var(text, name):
    match = re.search(r"^%s=(.*)$" % re.escape(name), text, re.M)
    if not match:
        return None
    value = match.group(1).strip()
    wrapped = re.match(r"^\$\{[A-Z_]+:-(.*)\}$", value)
    if wrapped:
        value = wrapped.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value


def _feature_keys(name):
    filename = "features.json" if name == "aarch64" else name + "-features.json"
    return list(json.loads((FEATURES / filename).read_text()))


def _target(name):
    return json.loads((TARGETS / (name + ".json")).read_text())


def _generic(name):
    doc = json.loads(DOMAIN.read_text())["targets"][name]
    spec = _target(name)
    return {
        "target": name,
        "source": spec["source"],
        "features": spec["features"],
        "runner": spec.get("domain") or "run-domain.sh",
        "configs": list(doc["configs"]),
        "queries": {"mode": "per_config", "value": doc["configs"]},
        "unanswerable": {"mode": "per_config",
                         "value": doc.get("unanswerable") or {}},
        "ref_asserts": {"mode": "per_config",
                        "value": doc.get("ref_asserts") or {}},
    }


def _special(name):
    script = (SCRIPTS / "domain" / ("run-%s-domain.sh" % name)).read_text()
    spec = _target(name)
    configs = _var(script, "CONFIGS")
    configs = configs.split() if configs else _feature_keys(name)
    total = _var(script, "EXPECTED_QUERIES")
    per_config = _var(script, "EXPECTED_PER_CONFIG")
    unanswerable = _var(script, "EXPECTED_UNANSWERABLE")
    unanswerable_map = _var(script, "EXPECTED_UNANSWERABLE_MAP")
    ref_asserts = _var(script, "EXPECTED_REF_ASSERTS")
    if total:
        queries = {"mode": "total", "value": int(total)}
    else:
        queries = {"mode": "per_config",
                   "value": {cfg: int(per_config) for cfg in configs}}
    if unanswerable_map:
        unanswerable = {"mode": "map",
                        "value": json.loads(unanswerable_map)}
    elif total:
        unanswerable = {"mode": "total", "value": int(unanswerable or 0)}
    elif unanswerable:
        unanswerable = {"mode": "per_config",
                        "value": {cfg: int(unanswerable) for cfg in configs}}
    else:
        unanswerable = {"mode": "per_config",
                        "value": {cfg: 0 for cfg in configs}}
    if total:
        ref_asserts = {"mode": "total", "value": int(ref_asserts or 0)}
    elif ref_asserts:
        ref_asserts = {"mode": "per_config",
                       "value": {cfg: int(ref_asserts) for cfg in configs}}
    else:
        ref_asserts = {"mode": "per_config",
                       "value": {cfg: 0 for cfg in configs}}
    return {
        "target": name,
        "source": spec["source"],
        "features": spec["features"],
        "runner": spec.get("domain") or ("run-%s-domain.sh" % name),
        "configs": configs,
        "queries": queries,
        "unanswerable": unanswerable,
        "ref_asserts": ref_asserts,
    }

def main(argv):
    if len(argv) != 2 or argv[1] not in SPECIAL | set(json.loads(DOMAIN.read_text())["targets"]):
        print("usage: domain-plan.py <target>", file=sys.stderr)
        return 2
    name = argv[1]
    plan = _special(name) if name in SPECIAL else _generic(name)
    json.dump(plan, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
