#!/usr/bin/env python3
"""Answer a query file, surviving the queries that make the runner abort.

    run-queries.py RUNNER QUERIES OUT [--report FILE]

A query that trips an LLVM assertion kills the process, and a buffered tail
would be lost.  The runner flushes per answer, so we restart after the query
that aborted and mark it `unanswerable` in the output.  The answer file stays
parallel to the query file, which is what `diff.py` needs.

The query file is fed in fixed-size chunks instead of re-writing "every
remaining line" on each abort.  A 960k-line domain aborts thousands of times;
rewriting the tail made that quadratic.  With chunks the write cost stays
O(lines) and each restart replays at most one chunk.

Neither the queries nor the answers are held in memory: both are streamed, so
peak RSS does not scale with the domain size.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from itertools import islice
from pathlib import Path

# A chunk is the unit of restart, not of semantics.  Large enough that the
# temp-file write is amortised, small enough that replaying the tail of a
# chunk after an abort is cheap.
CHUNK = 2000

# The runner recovers from most asserts in-process and writes `assert_site`
# itself.  These patterns cover the restart path: a hard crash that never
# reached the in-process handler still tells us where it died, and without the
# site a whole assert class collapses into one anonymous count.
_SITE_PATTERNS = (
    re.compile(r"UNREACHABLE executed at ([^:\s]+):(\d+)"),
    re.compile(r"([^\s:]+\.[A-Za-z]+):(\d+): (?:Assertion|assert)"),
)


def _assert_site(stderr):
    """`file:line` of the first assert/unreachable in a crashed runner."""
    for pattern in _SITE_PATTERNS:
        match = pattern.search(stderr or "")
        if match:
            return "%s:%s" % (os.path.basename(match.group(1)), match.group(2))
    return None


def _is_json(line):
    """True when a runner line is a complete JSON object."""
    try:
        json.loads(line)
    except ValueError:
        return False
    return True


def _lines(path):
    """Non-blank lines of a JSONL file, without their newline."""
    with path.open() as stream:
        for line in stream:
            if line.strip():
                yield line.rstrip("\n")


def run(runner, queries, out, report=None):
    total = sum(1 for _ in _lines(queries))
    aborted = bytearray(total)
    aborted_lines = []
    aborted_sites = {}

    raw_answers = tempfile.NamedTemporaryFile(
        "w", suffix=".answers", delete=False)
    try:
        base = 0
        stream = _lines(queries)
        chunk_lines = list(islice(stream, CHUNK))
        while chunk_lines:
            offset = 0
            while True:
                chunk_path = None
                try:
                    with tempfile.NamedTemporaryFile(
                            "w", suffix=".jsonl", delete=False) as handle:
                        chunk_path = handle.name
                        handle.write("\n".join(chunk_lines[offset:]) + "\n")
                    proc = subprocess.run(
                        [str(runner), "--queries", chunk_path],
                        capture_output=True, text=True)
                finally:
                    if chunk_path is not None:
                        Path(chunk_path).unlink()
                got = [line for line in proc.stdout.splitlines() if line.strip()]
                if proc.returncode == 0:
                    raw_answers.write("".join(line + "\n" for line in got))
                    break
                if proc.returncode not in (-6, -11, 134, 139):
                    # SIGABRT/SIGSEGV are the expected assertion deaths.
                    print("%s: exit %d on query %d:\n%s"
                          % (runner, proc.returncode, base + offset + len(got) + 1,
                             proc.stderr.strip()), file=sys.stderr)
                    return aborted_lines
                # A signal can land while the runner is writing its current
                # answer, leaving half a JSON object in stdout.  That partial
                # line belongs to the query that killed the process; it is not
                # an answer for it, and keeping it would shift every later
                # answer by one.
                if got and not _is_json(got[-1]):
                    got.pop()
                raw_answers.write("".join(line + "\n" for line in got))
                bad = base + offset + len(got)
                if bad >= base + len(chunk_lines):
                    bad = base + offset  # died before answering anything
                aborted[bad] = 1
                aborted_lines.append(bad)
                site = _assert_site(proc.stderr)
                if site:
                    aborted_sites[bad] = site
                offset = bad - base + 1
                if offset >= len(chunk_lines):
                    break
            base += len(chunk_lines)
            chunk_lines = list(islice(stream, CHUNK))
        raw_answers.flush()

        with out.open("w") as answer_stream, \
                open(raw_answers.name) as answered:
            for index, line in enumerate(_lines(queries)):
                if aborted[index]:
                    record = json.loads(line)
                    record["status"] = "unanswerable"
                    record["reason"] = "asserted"
                    site = aborted_sites.get(index)
                    if site:
                        record["assert_site"] = site
                    answer_stream.write(json.dumps(record) + "\n")
                    continue
                answer = answered.readline()
                # A short answer file leaves the query itself as the row; that
                # keeps the correspondence visible instead of silently
                # shifting every later row.
                answer_stream.write(answer if answer else line + "\n")
    finally:
        raw_answers.close()
        Path(raw_answers.name).unlink(missing_ok=True)

    if report is not None:
        report.write_text(json.dumps(
            {"queries": total, "answered": total - len(aborted_lines),
             "unanswerable": len(aborted_lines),
             "lines": [index + 1 for index in aborted_lines]}, indent=1) + "\n")
    print("%s: %d queries, %d unanswerable"
          % (runner, total, len(aborted_lines)), file=sys.stderr)
    return aborted_lines


def main(argv=None):
    parser = argparse.ArgumentParser(prog="run-queries")
    parser.add_argument("runner")
    parser.add_argument("queries")
    parser.add_argument("out")
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    run(Path(args.runner), Path(args.queries), Path(args.out),
        Path(args.report) if args.report else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
