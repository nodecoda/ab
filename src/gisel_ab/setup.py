"""`gisel-ab setup`: record the paths, so no one has to export them.

    gisel-ab setup --llvm DIR --build DIR [--evidence DIR]
    gisel-ab setup --show
    gisel-ab setup --unset build

The file is ``$XDG_CONFIG_HOME/gisel-ab/config.json`` (or
``~/.config/gisel-ab/config.json``); ``GISEL_AB_CONFIG`` moves it.  Resolution
stays flag > environment > config, so an existing shell setup keeps working.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gisel_ab import paths

KEYS = ("llvm", "build", "evidence")


def _validate(key: str, value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if key == "llvm":
        ok = (path / "llvm" / "include" / "llvm").is_dir()
        what = "an llvm-project checkout (llvm/include/llvm is missing)"
    elif key == "build":
        ok = (path / "build.ninja").is_file() or (path / "CMakeCache.txt").is_file()
        what = "an LLVM build dir (build.ninja or CMakeCache.txt is missing)"
    else:
        ok = (path / "EVIDENCE.json").is_file()
        what = "a fetched evidence dir (EVIDENCE.json is missing)"
    if not ok:
        print("input error: %s is not %s: %s" % (key, what, path),
              file=sys.stderr)
        raise SystemExit(2)
    return path


def _show() -> int:
    config = paths.load_config()
    print("config: %s" % paths.config_path())
    if not config:
        print("  (empty; the first run will create it)")
    for key in KEYS:
        if key in config:
            print("  %-8s = %s" % (key, config[key]))
    tree, where = paths.locate_tree()
    build, build_where = paths.locate_build()
    print("effective tree:  %s (%s)" % (tree or "unset", where or "default"))
    print("effective build: %s (%s)" % (build or "unset", build_where or "default"))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gisel-ab setup",
                                 description="record the LLVM paths in a config file")
    ap.add_argument("--llvm", help="llvm-project checkout")
    ap.add_argument("--build", help="configured ninja build directory")
    ap.add_argument("--evidence", help="a directory produced by `evidence fetch`")
    ap.add_argument("--unset", action="append", default=[], choices=KEYS)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args(argv)
    if args.show:
        return _show()
    config = paths.load_config()
    changed = False
    for key, value in (("llvm", args.llvm), ("build", args.build),
                       ("evidence", args.evidence)):
        if value:
            config[key] = str(_validate(key, value))
            changed = True
    for key in args.unset:
        if config.pop(key, None) is not None:
            changed = True
    if not changed:
        ap.error("nothing to do: pass --llvm/--build/--evidence, --unset or --show")
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    print("wrote %s" % path)
    for key in KEYS:
        if key in config:
            print("  %-8s = %s" % (key, config[key]))
    print("next: gisel-ab doctor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
