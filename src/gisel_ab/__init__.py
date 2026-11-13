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

import importlib.util
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


def _gisel_package_dir() -> Path | None:
    """The installed ``gisel`` package directory, when it is importable."""
    try:
        spec = importlib.util.find_spec("gisel")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations))).resolve()


def gisel_src(explicit=None) -> Path:
    """A directory that makes ``import gisel`` work.

    ``GISEL_SRC`` wins; then a sibling checkout; then the installed package,
    whose parent is the directory that belongs on ``sys.path``.  A path is
    returned even when nothing is found, so the caller's error names the
    place it looked.
    """
    value = explicit or os.environ.get("GISEL_SRC")
    if value:
        return Path(value).expanduser().resolve()
    sibling = (AB_ROOT.parent / "gisel").resolve()
    if (sibling / "gisel" / "__init__.py").is_file():
        return sibling
    package = _gisel_package_dir()
    if package is not None:
        return package.parent
    return sibling


def gisel_package() -> Path | None:
    """The ``gisel`` package directory, from a checkout or an install."""
    root = gisel_src()
    for candidate in (root / "gisel", root):
        if (candidate / "__init__.py").is_file():
            return candidate
    return _gisel_package_dir()


def gisel_data(name: str) -> Path | None:
    """The ``corpus``/``cases`` directory, checkout first, wheel second.

    The wheel ships byte-identical copies under ``gisel/data``; the checkout
    keeps the canonical copies under ``tests/``.
    """
    package = gisel_package()
    roots = [package.parent, package] if package is not None else [gisel_src()]
    for root in roots:
        for candidate in (root / "tests" / name,
                          root / "gisel" / "data" / name,
                          root / "data" / name):
            if candidate.is_dir():
                return candidate.resolve()
    return None


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
