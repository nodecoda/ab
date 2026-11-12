#!/usr/bin/env bash
set -euo pipefail

# run-wasm-end-to-end.sh TREE BUILD INC OUT
#
# One command, no manual steps: build both runners from INC, generate the
# fixed query set, answer it twice, and diff.  The query count is a contract:
# if the corpus or a feature axis changes it, stop and review the new
# questions.  942 = 4 configs x the 29 rule sets' witnessed points.
TREE=${1:?usage: run-wasm-end-to-end.sh TREE BUILD INC OUT}
BUILD=${2:?}
INC=${3:?}
OUT=${4:?}
. "$(cd "$(dirname "$0")" && pwd)/env.sh"
# 886 -> 894 on 2026-11-11: gisel 076c622 changes which indices a guarded
# `same_as` covers, so the G_ICMP rule-0 witness points and its samples move
# (i32 and s32 are the same LLT; the delta is confined to G_ICMP).
EXPECTED_QUERIES=894
mkdir -p "$OUT"

"$ROOT/build-wasm-runner.sh" "$TREE" "$BUILD" "$INC" "$OUT/runner"

python3 -m gisel cases "$GISEL/tests/corpus/WebAssemblyLegalizerInfo.gisel" \
  --features "$GISEL/tests/cases/wasm-features.json" \
  --out "$OUT/queries.jsonl" --json
GOT=$(wc -l < "$OUT/queries.jsonl")
if [[ "$GOT" != "$EXPECTED_QUERIES" ]]; then
  echo "query set changed: $GOT lines, expected $EXPECTED_QUERIES" >&2
  exit 1
fi

# A query that trips an LLVM assertion kills the process; run-queries.py
# restarts after it and marks it `unanswerable`, so the answer files stay
# parallel to the query file.
python3 "$ROOT/run-queries.py" "$OUT/runner.official" \
  "$OUT/queries.jsonl" "$OUT/official.answers.jsonl"
python3 "$ROOT/run-queries.py" "$OUT/runner.ours" \
  "$OUT/queries.jsonl" "$OUT/ours.answers.jsonl"
python3 "$ROOT/diff.py" "$OUT/official.answers.jsonl" \
  "$OUT/ours.answers.jsonl" --queries "$OUT/queries.jsonl" \
  --json | tee "$OUT/diff.json"
