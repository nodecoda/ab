"""gisel-ab: an A/B workbench around LLVM GlobalISel legalizer rules.

The package has one job: answer "does the legalizer this repository replaced
behave like the one it came from?"  Everything a caller needs to locate lives
here, so no module has to guess its depth in the tree.

    PKG       this package (code, data, cpp)
    AB_ROOT   the checkout that contains ``src/`` and ``scripts/``
    DATA      target registry, contracts, suite, domain  (package data)
    CPP       query-runner C++ sources                    (package data)
    SCRIPTS   the shell entry points                      (checkout only)
    EVIDENCE  the frozen evidence tree                    (checkout only)

``DATA`` and ``CPP`` travel with an installed wheel; ``SCRIPTS`` and
``EVIDENCE`` do not, and the commands that need them say so instead of
raising a FileNotFoundError three levels down.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent
SRC = PKG.parent
AB_ROOT = SRC.parent
DATA = PKG / "data"
CPP = PKG / "cpp"
SCRIPTS = AB_ROOT / "scripts"
EVIDENCE = AB_ROOT / "evidence"


def gisel_src(explicit=None) -> Path:
    """The gisel checkout that produces inc/queries.

    ``GISEL_SRC`` wins; otherwise the sibling ``gisel`` next to this checkout.
    """
    value = explicit or os.environ.get("GISEL_SRC")
    if value:
        return Path(value).expanduser().resolve()
    return (AB_ROOT.parent / "gisel").resolve()


def gisel_path_entry() -> str:
    """The ``sys.path`` entry that makes ``import gisel`` work."""
    return str(gisel_src())


def ensure_gisel_on_path() -> Path:
    path = gisel_src()
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)
    return path


def child_env(env=None) -> dict:
    """A copy of ``env`` (default: os.environ) that children can import from.

    Subprocesses are started as ``python3 -m gisel_ab.<verb>``; they need
    ``SRC`` on ``PYTHONPATH`` and gisel on it too unless it is installed.
    """
    out = dict(os.environ if env is None else env)
    parts = [str(SRC)]
    gisel = gisel_path_entry()
    if Path(gisel).is_dir():
        parts.append(gisel)
    current = out.get("PYTHONPATH")
    if current:
        parts.extend(part for part in current.split(os.pathsep) if part)
    out["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(parts))
    return out
