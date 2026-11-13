#!/usr/bin/env python3
"""Read and validate targets/*.json.

This is the only target registry.  The JSON Schema in targets/schema.json is
the contract; this module is a deliberately small validator for the subset of
JSON Schema that file uses (no third-party dependency).  Shell callers use
`env` so they never parse JSON themselves:

    eval "$(python3 targets.py env x86)"
    python3 targets.py get x86 diff_policy.expected_queries
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent
ROOT = PKG.parents[1]          # the checkout: state dirs and scripts live here
TARGET_DIR = PKG / "data" / "targets"
SCHEMA_PATH = TARGET_DIR / "schema.json"
SCRIPTS = ROOT / "scripts"
CPP = PKG / "cpp"
CONTRACTS = PKG / "data"


class TargetError(ValueError):
    pass


def _is_type(value, name):
    if name == "null":
        return value is None
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    raise TargetError("schema uses unsupported type %r" % name)


def _type_ok(value, spec):
    names = spec if isinstance(spec, list) else [spec]
    return any(_is_type(value, name) for name in names)


def validate(instance, schema, path="$"):
    """Return a list of 'path: message' strings; empty means valid."""
    errors = []
    if "type" in schema and not _type_ok(instance, schema["type"]):
        errors.append("%s: expected %s, got %s"
                      % (path, schema["type"], type(instance).__name__))
        return errors
    if "const" in schema and instance != schema["const"]:
        errors.append("%s: expected %r, got %r"
                      % (path, schema["const"], instance))
    if "enum" in schema and instance not in schema["enum"]:
        errors.append("%s: %r is not one of %r"
                      % (path, instance, schema["enum"]))
    if isinstance(instance, dict):
        for key in schema.get("required", ()):
            if key not in instance:
                errors.append("%s: missing field %r" % (path, key))
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    errors.append("%s: unknown field %r" % (path, key))
        for key, sub in props.items():
            if key in instance:
                errors.extend(validate(instance[key], sub,
                                       "%s.%s" % (path, key)))
    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            errors.extend(validate(item, schema["items"],
                                   "%s[%d]" % (path, index)))
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append("%s: shorter than %d"
                          % (path, schema["minLength"]))
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append("%s: %r does not match %s"
                          % (path, instance, schema["pattern"]))
    if isinstance(instance, int) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append("%s: %r is below %r"
                          % (path, instance, schema["minimum"]))
    for index, sub in enumerate(schema.get("allOf", ())):
        if "if" in sub:
            if not validate(instance, sub["if"], path):
                errors.extend(validate(instance, sub.get("then", {}), path))
        else:
            errors.extend(validate(instance, sub, "%s.allOf[%d]"
                                   % (path, index)))
    return errors


def load_schema():
    return json.loads(SCHEMA_PATH.read_text())


def check_document(doc, where):
    errors = validate(doc, load_schema())
    return ["%s: %s" % (where, error) for error in errors]


def check_file(path):
    path = Path(path)
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return ["%s: %s" % (path, exc)]
    return check_document(doc, path)


def check_all():
    errors = []
    for path in sorted(TARGET_DIR.glob("*.json")):
        if path.name == "schema.json":
            continue
        errors.extend(check_file(path))
    return errors


def names():
    return sorted(p.stem for p in TARGET_DIR.glob("*.json")
                  if p.name != "schema.json")


def load(name):
    path = TARGET_DIR / ("%s.json" % name)
    if not path.exists():
        known = names()
        raise TargetError("unknown target %r (known: %s)"
                          % (name, ", ".join(known) or "none"))
    doc = json.loads(path.read_text())
    errors = check_document(doc, path)
    if errors:
        raise TargetError("\n".join(errors))
    if doc["name"] != name:
        raise TargetError("%s: name is %r" % (path, doc["name"]))
    return doc


def lookup(doc, dotted):
    value = doc
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            raise TargetError("no such field %r" % dotted)
        value = value[part]
    return value


def shell_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (str, int)):
        return str(value)
    return json.dumps(value, sort_keys=True)


# The names are the contract with the shell scripts.  Add a name here and in
# the script that reads it, never one without the other.
SHELL_FIELDS = {
    "T_TARGET": "name",
    "T_SOURCE": "source",
    "T_FEATURES": "features",
    "T_AXES": "axes",
    "T_STRATEGY": "strategy",
    "T_BUILDER": "runner.builder",
    "T_NINJA_TARGET": "ninja_target",
    "T_LIBRARY": "library",
    "T_LIB_SNAPSHOT": "lib_snapshot",
    "T_U_BUILDER": "u_builder",
    "T_RUNNER_SOURCE": "runner.source",
    "T_INC_NAME": "inc_name",
    "T_ARTIFACT": "artifact",
    "T_TEST_DIR": "test_dir",
    "T_CONTRACT": "contract",
    "T_E2E": "e2e",
    "T_DOMAIN": "domain",
    "T_G_NEG": "g_neg",
    "T_U_NEG": "u_neg",
    "T_U_PREFIX": "u_prefix",
    "T_ALLOW_UNANSWERABLE": "allow_unanswerable",
    "T_QUERY_COUNT": "query_count",
    "T_EXPECTED_QUERIES": "diff_policy.expected_queries",
    "T_ALLOW_REF_ASSERTS": "diff_policy.allow_ref_asserts",
    "T_EXPECT_UNANSWERABLE": "diff_policy.expect_unanswerable",
    "T_L3": "l3",
    "T_MIR_SWAPPABLE": "mir.swappable",
}

# Targets name their runners, wrappers and contracts relative to the checkout
# so the JSON stays readable.  Shell callers `eval` this table and then run the
# value directly, so these fields must come out absolute.  AB_ROOT/AB_SCRIPTS/
# AB_CPP/AB_DATA let a caller point the table at another checkout: the shell
# entry points set them, and a test can build a fixture tree without copying
# the package.
def _repo_root() -> Path:
    return Path(os.environ.get("AB_ROOT") or ROOT).expanduser()


def _scripts_dir() -> Path:
    return Path(os.environ.get("AB_SCRIPTS") or (_repo_root() / "scripts")).expanduser()


def _dirs() -> dict:
    return {
        "T_BUILDER": _scripts_dir() / "runners",
        "T_U_BUILDER": _scripts_dir() / "runners",
        "T_E2E": _scripts_dir() / "e2e",
        "T_DOMAIN": _scripts_dir() / "domain",
        "T_RUNNER_SOURCE": Path(os.environ.get("AB_CPP") or CPP).expanduser(),
        "T_CONTRACT": Path(os.environ.get("AB_DATA") or CONTRACTS).expanduser(),
    }


def resolve_field(name, value):
    if value in (None, ""):
        return value
    directory = _dirs().get(name)
    if directory is None:
        return value
    return str(directory / Path(str(value)).name)


def shell_env(doc):
    lines = []
    for name, field in SHELL_FIELDS.items():
        value = shell_value(lookup(doc, field))
        lines.append("%s=%s" % (name, json.dumps(resolve_field(name, value))))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check", help="validate one file or all targets")
    p_check.add_argument("paths", nargs="*")
    p_get = sub.add_parser("get", help="print one field")
    p_get.add_argument("target")
    p_get.add_argument("field")
    p_env = sub.add_parser("env", help="print shell assignments")
    p_env.add_argument("target")
    args = parser.parse_args(argv)

    if args.cmd == "check":
        paths = args.paths or [p for p in sorted(TARGET_DIR.glob("*.json"))
                               if p.name != "schema.json"]
        errors = []
        for path in paths:
            errors.extend(check_file(path))
        for error in errors:
            print(error, file=sys.stderr)
        if errors:
            return 1
        print("targets: %d files valid" % len(paths))
        return 0

    try:
        doc = load(args.target)
        if args.cmd == "get":
            print(shell_value(lookup(doc, args.field)))
            return 0
        if args.cmd == "env":
            print(shell_env(doc))
            return 0
    except TargetError as exc:
        print("targets: %s" % exc, file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
