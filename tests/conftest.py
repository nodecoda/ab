"""Make the checkout testable without an install.

Two things used to work because every module sat at the repository root:
``import cohort`` and ``python3 diff.py``.  The package moved under ``src``,
so the suite puts ``src`` on the path, points ``GISEL_SRC`` at the sibling
checkout, and keeps the old flat names as aliases.  Aliases are import-time
only; nothing in the product depends on them.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
GISEL = Path(os.environ.get("GISEL_SRC") or (ROOT.parent / "gisel"))

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
os.environ.setdefault("GISEL_SRC", str(GISEL))

# Subprocess-based tests start `python3 -m gisel_ab.<verb>` with the inherited
# environment; give them the same path the interpreter has here.
_parts = [str(SRC), str(GISEL)]
_parts += [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
os.environ["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(_parts))

# Legacy flat module names -> package modules.  Pre-rename tests say
# `import cohort`; keeping the alias lets them exercise the same object.
_ALIASES = {
    "paths": "gisel_ab.paths",
    "targets": "gisel_ab.targets",
    "doctor": "gisel_ab.doctor",
    "cohort": "gisel_ab.cohort",
    "evidence": "gisel_ab.evidence",
    "baseline": "gisel_ab.baseline",
    "suite": "gisel_ab.suite",
    "l3": "gisel_ab.l3",
    "vertical": "gisel_ab.vertical",
    "domain_plan": "gisel_ab.domain_plan",
    "diff": "gisel_ab.l0.diff",
    "attribute": "gisel_ab.l0.attribute",
    "closure": "gisel_ab.l0.closure",
    "queries": "gisel_ab.l0.queries",
    "mir_libs": "gisel_ab.mir.libs",
}

for _alias, _module in _ALIASES.items():
    if _alias in sys.modules:
        continue
    try:
        sys.modules[_alias] = importlib.import_module(_module)
    except Exception:  # a missing gisel must not break collection
        pass
