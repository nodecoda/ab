#!/usr/bin/env python3
"""Replay the upstream legalizer MIR corpus against two CodeGen libraries.

    mir-replay.py --layer upstream --target x86 \\
        --tree TREE --build BUILD --out OUT --prepare [--json]

The command never patches the tree while replaying: ``--prepare`` builds the
official and replaced libraries once, restores the source, and replay runs the
same ``bin/llc`` twice with ``LD_LIBRARY_PATH`` pointing at either snapshot.

Buckets are disjoint and printed:

    runs = same + both_abort + diff + timeout + unsupported_run

``both_abort`` means both sides failed with identical output (a legalizer
`LLVM ERROR`, for example).  It is agreement, but it is counted separately so
a corpus full of aborts cannot look like a corpus full of transformations.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import difflib
import hashlib
import json
import re
import shlex
import shutil
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mir_libs  # noqa: E402

RUN_RE = re.compile(r"^\s*#\s*RUN:\s?(.*)$")
REDIRECT_RE = re.compile(r"^(?:\d*|&)(?:>>|>|<)$")
# `2>%t` and `2>%t.err` arrive as one token, `2> %t` as two.
REDIRECT_JOINED_RE = re.compile(r"^(?:\d*|&)(?:>>|>|<)\S+$")
REDIRECT_FD_RE = re.compile(r"^(?:\d*|&)>(?:&\d+)$")
# Pointer values, stack-frame addresses and machine-code addresses differ on
# every run even when both libraries behave identically.
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]+")
KNOWN_SUBST = ("%s", "%t")


def read_run_lines(path: Path) -> list[str]:
    """Return logical RUN directives, joining ``\\`` continuations."""
    commands = []
    for line in path.read_text(errors="replace").splitlines():
        match = RUN_RE.match(line)
        if match:
            commands.append(match.group(1))
    joined = []
    buffer = None
    for command in commands:
        buffer = command if buffer is None else buffer + " " + command
        if buffer.rstrip().endswith("\\"):
            buffer = buffer.rstrip()[:-1].rstrip()
            continue
        joined.append(buffer.strip())
        buffer = None
    if buffer is not None:
        joined.append(buffer.strip())
    return joined


def drop_redirects(tokens):
    """Remove `2> file`, `> file`, `< file` and `2>&1` from argv.

    The redirection target is a separate token after shlex splitting, so it
    has to be dropped together with the operator; leaving it behind turns it
    into an extra input file for `llc`.
    """
    kept = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if REDIRECT_RE.match(token):
            skip_next = True
            continue
        if REDIRECT_FD_RE.match(token):
            continue
        if REDIRECT_JOINED_RE.match(token):
            continue
        kept.append(token)
    return kept


def parse_run(command: str, source: Path, tmp: Path):
    """Turn one RUN line into ``(argv, expect_failure)`` or ``(None, reason)``.

    ``expect_failure`` is true for a ``not ...`` line: the corpus expects that
    command to fail, so the two sides must be compared on the failure text
    with run-to-run addresses removed, not on the raw bytes.
    """
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return None, "shlex: %s" % exc
    if "|" in tokens:
        tokens = tokens[:tokens.index("|")]
    expect_failure = False
    if tokens and tokens[0] == "not":
        # `not` may carry options before the command (`not --crash llc ...`).
        expect_failure = True
        tokens = tokens[1:]
        while tokens and not tokens[0].endswith("llc"):
            tokens = tokens[1:]
    if not tokens:
        return None, "empty"
    if not tokens[0].endswith("llc"):
        return None, "not an llc invocation: %s" % tokens[0]
    tokens = drop_redirects(tokens[1:])
    argv = []
    for token in tokens:
        for name in KNOWN_SUBST:
            if name in token:
                token = token.replace(name, str(source) if name == "%s" else str(tmp))
        if "%" in token:
            return None, "unknown substitution: %s" % token
        argv.append(token)
    legalizer = "-run-pass=legalizer" in argv
    if not legalizer and "-run-pass" in argv:
        index = argv.index("-run-pass")
        legalizer = index + 1 < len(argv) and argv[index + 1] == "legalizer"
    if not legalizer:
        return None, "not a legalizer run"
    if "-o" not in argv and "--output" not in argv:
        argv += ["-o", "-"]
    return argv, expect_failure


def discover(tree: Path, targets):
    found = []
    unsupported = []
    for target in targets:
        directory = tree / "llvm" / "test" / "CodeGen" / mir_libs.TEST_DIR[target]
        if not directory.is_dir():
            raise mir_libs.MirError("test directory not found: %s" % directory)
        for path in sorted(directory.rglob("*.mir")):
            runs = read_run_lines(path)
            if any("legalizer" in run for run in runs):
                found.append((target, path, runs))
    return found


def normalize(text: str) -> str:
    """Erase run-to-run addresses so crash output can be compared."""
    return ADDRESS_RE.sub("0x?", text)


def _diff_text(name, official, ours):
    lines = list(difflib.unified_diff(
        official.splitlines(keepends=True), ours.splitlines(keepends=True),
        fromfile="official/" + name, tofile="ours/" + name))
    return "".join(lines)


def replay_file(target: str, path: Path, runs, llc: Path,
                official_dir: Path, ours_dir: Path, out: Path,
                timeout: float, take_budget, tree: Path):
    key = hashlib.sha1(str(path).encode()).hexdigest()[:12]
    tmp = out / "tmp" / target / key
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    records = []
    for index, command in enumerate(runs, 1):
        pass_match = re.search(r"-run-pass[= ]+([A-Za-z0-9_-]+)", command)
        if not pass_match or pass_match.group(1) != "legalizer":
            records.append({"run": command, "status": "out_of_layer"})
            continue
        argv, extra = parse_run(command, path.resolve(),
                                tmp / ("run%d" % index))
        if argv is None:
            records.append({"run": command, "status": "unsupported_run",
                            "reason": extra})
            continue
        expect_failure = extra
        official = mir_libs.run_llc(llc, official_dir, argv, timeout,
                                    cwd=path.parent)
        ours = mir_libs.run_llc(llc, ours_dir, argv, timeout, cwd=path.parent)
        official_out, ours_out = normalize(official["out"]), normalize(ours["out"])
        official_err, ours_err = normalize(official["err"]), normalize(ours["err"])
        if official["timeout"] or ours["timeout"]:
            status = "timeout"
        elif (official["rc"], official_out, official_err) == (
                ours["rc"], ours_out, ours_err):
            status = "same" if official["rc"] == 0 else "both_abort"
        else:
            status = "diff"
        record = {
            "run": command,
            "status": status,
            "official_rc": official["rc"],
            "ours_rc": ours["rc"],
        }
        if expect_failure and status != "timeout":
            record["expect_failure"] = True
        if status == "diff":
            detail = None
            if take_budget():
                detail_path = out / "diffs" / (
                    "%s.%s.run%d.diff" % (target, key, index))
                detail_path.parent.mkdir(parents=True, exist_ok=True)
                body = (_diff_text("stdout", official_out, ours_out)
                        + _diff_text("stderr", official_err, ours_err))
                detail_path.write_text(body or "(no textual difference)\n")
                detail = str(detail_path)
            record["detail"] = detail
        records.append(record)
    return {"target": target, "path": str(path), "runs": records}


def run_replay(files, llc: Path, official_root: Path, ours_root: Path,
               out: Path, jobs: int, timeout: float, max_details: int,
               tree: Path):
    workers = max(1, min(jobs, len(files)))
    results = []
    remaining = [max_details]
    budget_lock = threading.Lock()

    def take_budget():
        with budget_lock:
            if remaining[0] <= 0:
                return False
            remaining[0] -= 1
            return True

    def one(item):
        target, path, runs = item
        return replay_file(target, path, runs, llc,
                           official_root / target, ours_root / target,
                           out, timeout, take_budget, tree)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(one, files):
            results.append(result)
    return results


def aggregate(results, targets):
    per_target = {name: {"files": 0, "all_run_lines": 0, "runs": 0,
                         "same": 0, "both_abort": 0, "diff": 0,
                         "timeout": 0, "unsupported_run": 0,
                         "out_of_layer": 0}
                  for name in targets}
    for result in results:
        row = per_target[result["target"]]
        row["files"] += 1
        for run in result["runs"]:
            row["all_run_lines"] += 1
            if run["status"] == "out_of_layer":
                row["out_of_layer"] += 1
                continue
            row["runs"] += 1
            row[run["status"]] += 1
    totals = {"all_run_lines": 0, "runs": 0, "same": 0, "both_abort": 0,
              "diff": 0, "timeout": 0, "unsupported_run": 0,
              "out_of_layer": 0}
    for row in per_target.values():
        for key in totals:
            totals[key] += row[key]
    return per_target, totals


def check_identity(totals):
    total = (totals["same"] + totals["both_abort"] + totals["diff"]
             + totals["timeout"] + totals["unsupported_run"])
    if total != totals["runs"]:
        raise mir_libs.MirError(
            "bucket identity broken: runs=%d sum=%d" % (totals["runs"], total))
    if totals["runs"] + totals["out_of_layer"] != totals["all_run_lines"]:
        raise mir_libs.MirError(
            "RUN-line identity broken: in_layer=%d out_of_layer=%d all=%d"
            % (totals["runs"], totals["out_of_layer"],
               totals["all_run_lines"]))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="mir-replay", description="Replay legalizer MIR against two libraries")
    parser.add_argument("--layer", choices=("upstream",), default="upstream")
    parser.add_argument("--target", action="append", default=[],
                        choices=mir_libs.SWAPPABLE)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--gisel", default=str(mir_libs.DEFAULT_GISEL))
    parser.add_argument("--llc")
    parser.add_argument("--jobs", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-details", type=int, default=10)
    parser.add_argument("--prepare", action="store_true",
                        help="snapshot official, build ours, restore baseline")
    parser.add_argument("--negative-control", metavar="OPCODE",
                        help="build a mutant include and require diff > 0")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    tree = Path(args.tree).resolve()
    build = Path(args.build).resolve()
    out = Path(args.out).resolve()
    gisel = Path(args.gisel).resolve()
    targets = args.target or list(mir_libs.SWAPPABLE)
    llc = Path(args.llc).resolve() if args.llc else build / "bin" / "llc"
    side = "ours-negative" if args.negative_control else "ours"
    out.mkdir(parents=True, exist_ok=True)

    try:
        with mir_libs.Lock(out / "lock"):
            provenance = {
                "schema": 1,
                "layer": args.layer,
                "tree": str(tree),
                "build": str(build),
                "git_head": mir_libs.git_head(tree),
                "llc": str(llc),
                "llc_sha256": mir_libs.sha256(llc),
                "targets": {},
            }
            if args.prepare:
                for target in targets:
                    provenance["targets"][target] = mir_libs.prepare_target(
                        target, tree, build, out, gisel,
                        mutate_opcode=args.negative_control)
            else:
                for target in targets:
                    spec = mir_libs.load_target(target)
                    official = out / "official" / target / Path(spec["library"]).name
                    ours = out / side / target / Path(spec["library"]).name
                    if not official.exists() or not ours.exists():
                        raise mir_libs.MirError(
                            "missing snapshots for %s; run with --prepare" % target)
                    provenance["targets"][target] = {
                        "official_lib_sha256": mir_libs.sha256(official),
                        "ours_lib_sha256": mir_libs.sha256(ours),
                    }
            (out / "provenance.json").write_text(
                json.dumps(provenance, indent=2) + "\n")

            files = discover(tree, targets)
            started = time.time()
            results = run_replay(files, llc, out / "official",
                                 out / side, out, args.jobs, args.timeout,
                                 args.max_details, tree)
            per_target, totals = aggregate(results, targets)
            check_identity(totals)

            report = {
                "schema": 1,
                "layer": args.layer,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                              time.gmtime()),
                "elapsed_seconds": round(time.time() - started, 3),
                "llc": str(llc),
                "llc_sha256": provenance["llc_sha256"],
                "negative_control": args.negative_control,
                "totals": totals,
                "targets": per_target,
                "inputs": {
                    "official_libs": {
                        name: provenance["targets"][name].get(
                            "official_lib_sha256")
                        for name in targets},
                    "ours_libs": {
                        name: provenance["targets"][name].get(
                            "ours_lib_sha256")
                        for name in targets},
                },
                "files": results,
            }
            report_path = out / "mir-report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n")

            if args.json:
                print(json.dumps({"totals": totals, "targets": per_target,
                                  "negative_control": args.negative_control},
                                 indent=2))
            else:
                print("layer=%s targets=%s" % (args.layer, ",".join(targets)))
                for name in targets:
                    row = per_target[name]
                    print("  %-9s files=%d in_layer=%d same=%d "
                          "both_abort=%d diff=%d timeout=%d unsupported=%d "
                          "out_of_layer=%d"
                          % (name, row["files"], row["runs"], row["same"],
                             row["both_abort"], row["diff"], row["timeout"],
                             row["unsupported_run"], row["out_of_layer"]))
                print("  totals    in_layer=%d same=%d both_abort=%d diff=%d "
                      "timeout=%d unsupported=%d out_of_layer=%d"
                      % (totals["runs"], totals["same"], totals["both_abort"],
                         totals["diff"], totals["timeout"],
                         totals["unsupported_run"], totals["out_of_layer"]))
                print("report=%s" % report_path)

            if args.negative_control:
                caught = totals["diff"] > 0
                print("negative-control %s: %s (diff=%d)"
                      % (args.negative_control,
                         "caught" if caught else "NOT CAUGHT", totals["diff"]))
                return 0 if caught else 1
            return 0 if totals["diff"] == 0 else 1
    except mir_libs.MirError as exc:
        print("mir-replay: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
