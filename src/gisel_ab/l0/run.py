#!/usr/bin/env python3
"""AB harness: one command for the LLVM legalizer differential loop.

    ab.py run --target x86 --tree TREE --build BUILD \
        --source <gisel>/tests/corpus/X86LegalizerInfo.gisel \
        --features <gisel>/tests/cases/x86-features.json \
        --queries QUERIES.jsonl --out OUT [--compare action|full]

This is the workbench side of the boundary in ``docs/SCOPE.md``: it consumes
the ``.inc`` and answerless queries produced by gisel, builds the official and
the replaced legalizer, runs both over one query file, and compares the
answers.  It imports only ``gisel.jsonl`` (the stable JSONL contract); it
does not call an LLM and it does not change gisel's command surface.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parent
AB_ROOT = PKG.parents[2]
GISEL = Path(os.environ.get("GISEL_SRC", AB_ROOT.parent / "gisel")).resolve()
CPP = PKG.parent / "cpp"
SCRIPTS = AB_ROOT / "scripts"
os.environ["PYTHONPATH"] = str(GISEL) + (
    os.pathsep + os.environ["PYTHONPATH"]
    if os.environ.get("PYTHONPATH") else "")
sys.path.insert(0, str(GISEL))

from gisel import jsonl as J  # noqa: E402

from gisel_ab import child_env  # noqa: E402
from gisel_ab import paths  # noqa: E402
from gisel_ab import targets as target_registry  # noqa: E402
from gisel_ab.l0 import attribute  # noqa: E402

NINJA = os.environ.get("NINJA", "ninja")


class HarnessError(RuntimeError):
    pass


def _sha_prefix(value, width: int = 12) -> str:
    """A sha for humans, `none` when the target has no such baseline."""
    return value[:width] if value else "none"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text())


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_target(name: str) -> dict:
    """Load one validated targets/<name>.json; no embedded tables."""
    try:
        return target_registry.load(name)
    except target_registry.TargetError as exc:
        raise HarnessError(str(exc))


def git_head(tree: Path) -> str:
    proc = subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    if proc.returncode:
        raise HarnessError("cannot read git HEAD from %s: %s"
                           % (tree, proc.stderr.strip()))
    return proc.stdout.strip()


def run_capture(cmd, cwd=None, env=None):
    merged = child_env()
    if env:
        merged.update(env)
    return subprocess.run([str(part) for part in cmd], cwd=str(cwd or AB_ROOT),
                          capture_output=True, text=True, env=merged)


def run_checked(cmd, cwd=None, env=None):
    proc = run_capture(cmd, cwd, env)
    if proc.returncode:
        raise HarnessError("command failed (%d): %s\n%s"
                           % (proc.returncode,
                              " ".join(str(part) for part in cmd),
                              proc.stderr.strip()))
    return proc


def ninja(build: Path, target: str):
    run_checked([NINJA, "-C", build, target])


def touch(path: Path):
    os.utime(path, None)


class Lock:
    """One writer per state directory; flock is released on process exit."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self):
        self.handle = open(self.path, "w")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.handle.close()
            raise HarnessError("another run holds %s" % self.path)
        self.handle.write(str(os.getpid()))
        self.handle.flush()
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()
        return False


def validate_queries(path: Path, features_path: Path, expected=None) -> int:
    try:
        table = J.load_features(str(features_path)).table
    except (OSError, ValueError, J.EvalError) as exc:
        raise HarnessError("cannot read features %s: %s"
                           % (features_path, exc))
    seen = set()
    count = 0
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                q = json.loads(line)
            except ValueError as exc:
                raise HarnessError("%s:%d: %s" % (path, lineno, exc))
            mem = q.get("mem")
            if mem is not None and len(mem) not in (2, 4):
                raise HarnessError("%s:%d: mem must be null, 2-tuple or "
                                   "4-tuple" % (path, lineno))
            try:
                key = J.key(q)
            except (KeyError, TypeError, ValueError, J.EvalError) as exc:
                raise HarnessError("%s:%d: %s" % (path, lineno, exc))
            if key[0] not in table:
                raise HarnessError("%s:%d: unknown config %r"
                                   % (path, lineno, key[0]))
            if key in seen:
                raise HarnessError("%s:%d: duplicate query key"
                                   % (path, lineno))
            seen.add(key)
            count += 1
    if expected is not None and count != expected:
        raise HarnessError("%s: %d queries, expected %d"
                           % (path, count, expected))
    return count


def ensure_baseline(target: dict, tree: Path, build: Path, state: Path,
                    refresh: bool = False) -> tuple[Path, dict]:
    base = state / "baseline"
    # Hand-written legalizers (RISCV) have no generated inc in the build; the
    # official constructor lives in the library, so that sha is the anchor.
    rel_inc = target.get("baseline_inc")
    inc = build / rel_inc if rel_inc else None
    if inc is not None and not inc.exists():
        raise HarnessError("baseline inc not found: %s" % inc)
    lib = build / target["library"]
    current = {
        "tree": str(tree),
        "build": str(build),
        "git_head": git_head(tree),
        "inc_sha256": sha256(inc) if inc is not None else None,
        "lib_sha256": sha256(lib) if lib.exists() else None,
    }
    prov_path = base / "provenance.json"
    if prov_path.exists() and not refresh:
        prov = read_json(prov_path)
        if prov.get("inc_sha256") != current["inc_sha256"]:
            raise HarnessError(
                "baseline inc changed (%s -> %s); pass --refresh-baseline"
                % (_sha_prefix(prov.get("inc_sha256")),
                   _sha_prefix(current["inc_sha256"])))
        if prov.get("git_head") != current["git_head"]:
            raise HarnessError(
                "baseline tree HEAD changed (%s -> %s); pass --refresh-baseline"
                % (prov.get("git_head", "?")[:12],
                   current["git_head"][:12]))
        if (prov.get("lib_sha256") is not None
                and prov["lib_sha256"] != current["lib_sha256"]):
            raise HarnessError(
                "baseline library changed (%s -> %s); pass --refresh-baseline"
                % (prov["lib_sha256"][:12],
                   (current["lib_sha256"] or "?")[:12]))
        return base, prov
    base.mkdir(parents=True, exist_ok=True)
    if inc is not None:
        shutil.copyfile(inc, base / target["inc_name"])
    if lib.exists():
        shutil.copyfile(lib, base / lib.name)
    prov_path.write_text(json.dumps(current, indent=2) + "\n")
    return base, current


def generate_inc(target: dict, source: Path, out: Path) -> Path:
    dest = out / target["inc_name"]
    run_checked([sys.executable, "-m", "gisel", "gen", source,
                 "--emit=inc", "--out", dest])
    if not dest.exists():
        raise HarnessError("gisel gen did not write %s" % dest)
    return dest


def build_swap_runner(target: dict, tree: Path, build: Path, out: Path,
                      name: str, skip_pin: bool = False) -> Path:
    """Build a query runner against the library currently in BUILD.

    `skip_pin` is for the replaced (ours) library: the tree is patched at that
    moment, so a content check would reject our own include.  The caller must
    have checked the restored tree before patching.
    """
    builder = SCRIPTS / "runners" / target["runner"]["builder"]
    runner = out / name
    env = {"GIT_DSL_SKIP_PIN_CHECK": "1"} if skip_pin else None
    run_checked(["bash", builder, tree, build, runner,
                 target["runner"].get("mode", "shipping")], env=env)
    return runner


def build_ctor_runners(target: dict, tree: Path, build: Path, inc: Path,
                       out: Path) -> tuple[Path, Path]:
    builder = SCRIPTS / "runners" / target["runner"]["builder"]
    prefix = out / "runner"
    run_checked(["bash", builder, tree, build, inc, prefix])
    return out / "runner.official", out / "runner.ours"


def answer(runner: Path, queries: Path, out: Path):
    run_checked([sys.executable, "-m", "gisel_ab.l0.queries",
                 runner, queries, out])



def swap_source(mode: str, target: dict, tree: Path, inc: Path | None = None):
    """Patch the constructor body to include `inc` (or restore the original).

    `swap-source-ctor.py` keeps the untouched file under `TREE/.gisel-swap`, so
    restore is byte exact even if the run dies in the middle.
    """
    cmd = [sys.executable, "-m", "gisel_ab.l0.swap", mode,
           "--target", target["name"], "--tree", tree]
    if mode == "apply":
        cmd += ["--inc", inc]
    proc = run_capture(cmd)
    if proc.returncode:
        raise HarnessError("swap-source-ctor %s failed: %s"
                           % (mode, proc.stderr.strip()))


def generate_core(target: dict, source: Path, out: Path) -> Path:
    dest = out / "core.json"
    run_checked([sys.executable, "-m", "gisel", "gen", source,
                 "--emit=core", "--out", dest])
    return dest


def run_eval(core: Path, features: Path, queries: Path, out: Path) -> tuple[Path, int]:
    dest = out / "eval.answers.jsonl"
    proc = run_capture([sys.executable, "-m", "gisel", "eval",
                        "--doc", core, "--features", features,
                        "--cases", queries, "--answers", dest])
    if proc.returncode not in (0, 1):
        raise HarnessError("gisel eval failed: %s" % proc.stderr.strip())
    return dest, proc.returncode


def compare(target: dict, ref: Path, ours: Path, out: Path, mode: str,
            queries: Path | None = None):
    cmd = [sys.executable, "-m", "gisel_ab.l0.diff",
           ref, ours, "--json", "--compare", mode,
           "--details", "1000000"]
    if queries is not None:
        cmd += ["--queries", str(queries)]
    policy = target.get("diff_policy") or {}
    if policy.get("allow_ref_asserts") is not None:
        cmd += ["--allow-ref-asserts", str(policy["allow_ref_asserts"])]
    if policy.get("expect_unanswerable") is not None:
        cmd += ["--expect-unanswerable", str(policy["expect_unanswerable"])]
    proc = run_capture(cmd)
    (out / "diff.json").write_text(proc.stdout)
    if proc.returncode == 2:
        raise HarnessError("diff failed: %s" % proc.stderr.strip())
    try:
        result = json.loads(proc.stdout)
    except ValueError as exc:
        raise HarnessError("diff produced invalid JSON: %s" % exc)
    return proc.returncode, result


def append_ledger(state: Path, record: dict):
    with open(state / "ledger.jsonl", "a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def cmd_run(args) -> int:
    target = load_target(args.target)
    tree = (Path(args.tree).expanduser().resolve() if args.tree
            else paths.require_tree())
    build = (Path(args.build).expanduser().resolve() if args.build
             else paths.require_build())
    out = Path(args.out).resolve()
    state = Path(args.state or (AB_ROOT / ".ab" / target["name"])).resolve()
    source = Path(args.source or (GISEL / target["source"])).resolve()
    features = Path(args.features or (GISEL / target["features"])).resolve()
    queries = Path(args.queries).resolve()
    if not tree.is_dir():
        raise HarnessError("tree not found: %s" % tree)
    if not build.is_dir():
        raise HarnessError("build not found: %s" % build)
    if not queries.exists():
        raise HarnessError("queries not found: %s" % queries)
    if not args.inc and not source.exists():
        raise HarnessError("source not found: %s" % source)
    if not features.exists():
        raise HarnessError("features not found: %s" % features)
    out.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    with Lock(state / "lock"):
        count = validate_queries(queries, features, target.get("query_count"))
        _baseline, prov = ensure_baseline(target, tree, build, state,
                                          args.refresh_baseline)
        if args.inc:
            inc = out / target["inc_name"]
            shutil.copyfile(Path(args.inc).resolve(), inc)
        else:
            inc = generate_inc(target, source, out)
        inc_sha = sha256(inc)
        record = {
            "run_id": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                      + "-" + target["name"],
            "target": target["name"],
            "strategy": target["strategy"],
            "tree": str(tree),
            "build": str(build),
            "git_head": prov["git_head"],
            "source": str(source) if not args.inc else None,
            "inc": str(inc),
            "inc_sha256": inc_sha,
            "baseline_inc_sha256": prov["inc_sha256"],
            "features": str(features),
            "queries": str(queries),
            "query_sha256": sha256(queries),
            "query_count": count,
            "compare": args.compare,
        }
        core = None
        if not args.no_eval:
            if args.core:
                core = Path(args.core).resolve()
            elif args.inc:
                raise HarnessError("--core is required with --inc when eval is on")
            else:
                core = generate_core(target, source, out)
        if args.dry_run:
            print("target=%s strategy=%s tree=%s build=%s"
                  % (target["name"], target["strategy"], tree, build))
            print("inc=%s sha256=%s" % (inc, inc_sha[:16]))
            print("baseline_inc_sha256=%s" % _sha_prefix(prov["inc_sha256"],
                                                         16))
            print("queries=%s count=%d compare=%s"
                  % (queries, count, args.compare))
            print("eval=%s core=%s" % (not args.no_eval, core))
            print("out=%s state=%s" % (out, state))
            return 0

        official = out / "official.answers.jsonl"
        ours = out / "ours.answers.jsonl"
        cache_dir = state / "cache" / "official"
        cache_dir.mkdir(parents=True, exist_ok=True)
        runner_source = CPP / Path(target["runner"]["source"]).name
        cache_key = sha256_text(json.dumps({
            "target": target["name"],
            "git_head": prov["git_head"],
            "baseline_inc_sha256": prov["inc_sha256"],
            "lib_sha256": prov.get("lib_sha256"),
            "build_config": (sha256(build / "CMakeCache.txt")
                             if (build / "CMakeCache.txt").exists() else None),
            "query_sha256": sha256(queries),
            "runner_source_sha256": sha256(runner_source),
        }, sort_keys=True))
        cache_path = cache_dir / (cache_key + ".jsonl")
        cache_hit = (not args.no_cache) and cache_path.exists()
        record["official_cache"] = "off" if args.no_cache else (
            "hit" if cache_hit else "miss")
        rc = 0
        if target["strategy"] == "swap-source":
            swap_source("restore", target, tree)   # no backup yet is fine
            ninja(build, target["ninja_target"])
            if cache_hit:
                shutil.copyfile(cache_path, official)
            else:
                runner = build_swap_runner(target, tree, build, out,
                                           "runner.official")
                answer(runner, queries, official)
                record["official_runner_sha256"] = sha256(runner)
                shutil.copyfile(official, cache_path)
            body_error = None
            try:
                run_checked([SCRIPTS / "check-pin.sh", tree])
                swap_source("apply", target, tree, inc)
                ninja(build, target["ninja_target"])
                runner = build_swap_runner(target, tree, build, out,
                                           "runner.ours", skip_pin=True)
                record["ours_runner_sha256"] = sha256(runner)
                answer(runner, queries, ours)
            except BaseException as exc:  # keep the tree restorable
                body_error = exc
            try:
                swap_source("restore", target, tree)
                ninja(build, target["ninja_target"])
            except BaseException as exc:
                raise HarnessError("restore failed after run: %s" % exc)
            if body_error is not None:
                raise body_error
        elif target["strategy"] == "generated-ctor":
            runner_official, runner_ours = build_ctor_runners(
                target, tree, build, inc, out)
            record["official_runner_sha256"] = sha256(runner_official)
            record["ours_runner_sha256"] = sha256(runner_ours)
            if cache_hit:
                shutil.copyfile(cache_path, official)
            else:
                answer(runner_official, queries, official)
                shutil.copyfile(official, cache_path)
            answer(runner_ours, queries, ours)
        else:
            raise HarnessError("unknown strategy %r" % target["strategy"])

        rc, result = compare(target, official, ours, out, args.compare,
                             queries)
        if not args.no_eval:
            eval_answers, eval_rc = run_eval(core, features, queries, out)
            record["eval_rc"] = eval_rc
            query_map = attribute.load_queries(queries,
                                              J.load_features(features))
            official_map, e1 = J.load(official)
            ours_map, e2 = J.load(ours)
            eval_map, e3 = J.load(eval_answers)
            bundle = attribute.build_bundle(
                result, J.load_features(features),
                query_map, official_map, ours_map, eval_map)
            bundle["summary"]["reader_errors"] = e1 + e2 + e3
            bundle_dir = Path(args.bundle).resolve() if args.bundle else (out / "bundle")
            attribute.write_bundle(bundle, bundle_dir)
            record["bundle"] = str(bundle_dir)
            record["matrix"] = bundle["summary"]["matrix"]
        record["diff"] = {
            key: result[key] for key in
            ("mode", "ref", "ours", "matched", "agree", "disagree",
             "unanswerable", "missing_ref", "missing_ours", "errors")
        }
        record["first_classes"] = {
            cls: sum(1 for item in result.get("first_details", [])
                     if item["class"] == cls)
            for cls in ("status", "action", "type_idx", "new_type")
        }
        record["rc"] = rc
        append_ledger(state, record)
        print("target=%s compare=%s queries=%d agree=%d disagree=%d "
              "unanswerable=%d missing_ref=%d missing_ours=%d rc=%d"
              % (target["name"], args.compare, result["matched"],
                 result["agree"], result["disagree"],
                 result["unanswerable"], result["missing_ref"],
                 result["missing_ours"], rc))
        print("official=%s" % official)
        print("ours=%s" % ours)
        print("diff=%s" % (out / "diff.json"))
        return rc


def cmd_verify(args) -> int:
    target = load_target(args.target)
    tree = (Path(args.tree).expanduser().resolve() if args.tree
            else paths.require_tree())
    build = (Path(args.build).expanduser().resolve() if args.build
             else paths.require_build())
    state = Path(args.state or (AB_ROOT / ".ab" / target["name"])).resolve()
    prov_path = state / "baseline" / "provenance.json"
    if not prov_path.exists():
        raise HarnessError("no baseline in %s" % state)
    prov = read_json(prov_path)
    rel_inc = target.get("baseline_inc")
    if not rel_inc:
        # Hand-written and generated-ctor targets have no generated inc in the
        # build; the original constructor lives in the library, so the library
        # sha is the anchor the baseline recorded.
        expected = prov.get("lib_sha256")
        if not expected:
            raise HarnessError(
                "%s: the baseline recorded neither an inc nor a library sha"
                % target["name"])
        lib = build / target["library"]
        if not lib.exists():
            raise HarnessError("baseline library not found: %s" % lib)
        got = sha256(lib)
        ok = got == expected
        print("lib=%s sha256=%s baseline=%s %s"
              % (lib, got[:16], expected[:16], "OK" if ok else "MISMATCH"))
        return 0 if ok else 1
    inc = build / rel_inc
    if not inc.exists():
        raise HarnessError("baseline inc not found: %s" % inc)
    got = sha256(inc)
    ok = got == prov["inc_sha256"]
    print("inc=%s sha256=%s baseline=%s %s"
          % (inc, got[:16], _sha_prefix(prov["inc_sha256"], 16),
             "OK" if ok else "MISMATCH"))
    return 0 if ok else 1


def cmd_doctor(args) -> int:
    import doctor
    argv = ["--json"] if args.json else []
    if args.tree:
        argv += ["--tree", args.tree]
    if args.build:
        argv += ["--build", args.build]
    return doctor.main(argv)


def cmd_mir(args) -> int:
    """L2: answerless queries -> minimal MIR -> replay against both libraries.

    The MIR builder preflights each file by parsing it with the *baseline*
    llc, which is what the build directory holds at rest (prepare_target
    restores it in ``finally``).  The replay step then builds both sides once
    and compares them; a failure there is the L2 verdict.
    """
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    tree = (Path(args.tree).expanduser().resolve() if args.tree
            else paths.require_tree())
    build = (Path(args.build).expanduser().resolve() if args.build
             else paths.require_build())
    llc = Path(args.llc) if args.llc else build / "bin" / "llc"
    mir_dir = out / "mir"
    builder = ["-m", "gisel_ab.mir.from_query"]
    replay = ["-m", "gisel_ab.mir.replay"]

    build_cmd = [sys.executable, *builder, "--target", args.target,
                 "--queries", str(Path(args.queries).resolve()),
                 "--out", str(mir_dir), "--preflight-llc", str(llc),
                 "--jobs", str(args.jobs)]
    if args.limit:
        build_cmd += ["--limit", str(args.limit)]
    if args.shapes:
        build_cmd += ["--shapes", str(Path(args.shapes).resolve())]
    if args.configs:
        build_cmd += ["--configs", str(Path(args.configs).resolve())]
    status = subprocess.call(build_cmd)
    if status != 0:
        print("ab: MIR builder failed (rc=%d)" % status, file=sys.stderr)
        return status

    replay_cmd = [sys.executable, *replay, "--layer", "generated",
                  "--mir", str(mir_dir), "--target", args.target,
                  "--tree", str(tree), "--build", str(build),
                  "--out", str(out / "replay"), "--prepare",
                  "--jobs", str(args.jobs), "--timeout", str(args.timeout)]
    if args.negative_control:
        replay_cmd += ["--negative-control", args.negative_control]
    if args.expect_timeouts is not None:
        replay_cmd += ["--expect-timeouts", str(args.expect_timeouts)]
    if args.expect_unsupported is not None:
        replay_cmd += ["--expect-unsupported", str(args.expect_unsupported)]
    if args.json:
        replay_cmd.append("--json")
    return subprocess.call(replay_cmd)


def build_parser():
    ap = argparse.ArgumentParser(
        prog="ab.py",
        description="AB harness for the LLVM legalizer differential loop")
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="build both sides, answer, diff, restore")
    run.add_argument("--target", required=True,
                     help="adapter name under targets/")
    run.add_argument("--tree", help="LLVM source tree (default: flag > env > setup)")
    run.add_argument("--build", help="LLVM build directory (default: flag > env > setup)")
    run.add_argument("--queries", required=True,
                     help="answerless query JSONL")
    run.add_argument("--out", required=True, help="artifact directory")
    run.add_argument("--source", help=".gisel source (default: adapter)")
    run.add_argument("--inc", help="prebuilt inc, skip gisel gen")
    run.add_argument("--features",
                     help="feature truth table (default: adapter)")
    run.add_argument("--state", help="baseline/ledger directory")
    run.add_argument("--compare", choices=("action", "full"), default="full",
                     help="action: smoke; full: acceptance (default)")
    run.add_argument("--refresh-baseline", action="store_true",
                     help="replace a stale baseline snapshot")
    run.add_argument("--dry-run", action="store_true",
                     help="validate inputs, generate inc, print plan")
    run.add_argument("--core", help="prebuilt core JSON (default: gisel gen)")
    run.add_argument("--bundle",
                     help="bundle directory (default: OUT/bundle)")
    run.add_argument("--no-eval", action="store_true",
                     help="skip the three-way eval matrix")
    run.add_argument("--no-cache", action="store_true",
                     help="do not reuse official answers")
    run.set_defaults(func=cmd_run)

    mir = sub.add_parser(
        "mir", help="L2: turn answerless queries into MIR, then replay them")
    mir.add_argument("--target", required=True)
    mir.add_argument("--queries", required=True,
                     help="answerless query JSONL (gisel cases output)")
    mir.add_argument("--tree", help="LLVM source tree (default: flag > env > setup)")
    mir.add_argument("--build", help="LLVM build directory (default: flag > env > setup)")
    mir.add_argument("--out", required=True, help="artifact directory")
    mir.add_argument("--llc", help="llc to preflight with (default: BUILD/bin)")
    mir.add_argument("--shapes", help="override data/mir-shapes.jsonc")
    mir.add_argument("--configs", help="override data/mir-configs.json")
    mir.add_argument("--negative-control", metavar="OPCODE",
                     help="neutralise one opcode; the replay must catch it")
    mir.add_argument("--limit", type=int)
    mir.add_argument("--jobs", type=int, default=16)
    mir.add_argument("--timeout", type=float, default=60.0)
    mir.add_argument("--expect-timeouts", type=int, default=None, metavar="N",
                     help="exact number of timed-out runs; default: fail on any")
    mir.add_argument("--expect-unsupported", type=int, default=None,
                     metavar="N",
                     help="exact number of non-replayable RUN lines; "
                          "default: fail on any")
    mir.add_argument("--json", action="store_true")
    mir.set_defaults(func=cmd_mir)

    verify = sub.add_parser("verify", help="check the build is back on baseline")
    verify.add_argument("--target", required=True)
    verify.add_argument("--tree", help="LLVM source tree (default: flag > env > setup)")
    verify.add_argument("--build", help="LLVM build directory (default: flag > env > setup)")
    verify.add_argument("--state")
    verify.set_defaults(func=cmd_verify)

    doc = sub.add_parser(
        "doctor",
        help="check tree/build/gisel/state before a run (read-only)")
    doc.add_argument("--tree", help="LLVM checkout (default: AB_TREE)")
    doc.add_argument("--build", help="ninja build (default: AB_BUILD)")
    doc.add_argument("--json", action="store_true")
    doc.set_defaults(func=cmd_doctor)

    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except HarnessError as exc:
        print("ab: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
