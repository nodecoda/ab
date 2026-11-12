#!/usr/bin/env bash
set -euo pipefail

# run-spirv-end-to-end.sh TREE BUILD INC OUT
#
# One command, no manual steps: build both runners from INC, generate the
# fixed query set, answer it twice, and diff.  The query count is a contract:
# if the corpus changes it, stop and review the new questions.
#
# 5,136 -> 5,734 on 2026-11-10: the case generator started rejecting type
# tuples MIR cannot hold (`9e59c9d`, `77bcb7b`), so the set was regenerated and
# re-reviewed (unique keys, deterministic, every rule still witnessed).
# The four unanswerable queries are a shared assert: SPIRVLegalizerInfo.cpp
# passes `MaxVectorSize` where `changeElementSizeTo` expects a type index
# (`changeElementCountTo(0, ElementCount::getFixed(...))` was meant), so both
# sides abort on G_SPLAT_VECTOR with 32 elements.  `--expect-unanswerable 4`
# pins the count; a new class of assert cannot hide there.  See
# docs/REPORT-cxx-corpus.md and admin/upstream-issues.
TREE=${1:?usage: run-spirv-end-to-end.sh TREE BUILD INC OUT}
BUILD=${2:?}
INC=${3:?}
OUT=${4:?}
. "$(cd "$(dirname "$0")" && pwd)/env.sh"
# 5,734 -> 5,689 on 2026-11-12: `numElementsNotPow2` now translates with the
# upstream `isFixedVector()` half, so the scalarize rule stops claiming
# scalable vectors and its witness points shrink (U-full found the 400 keys
# that were answered differently).
EXPECTED_QUERIES=5689
mkdir -p "$OUT"

"$ROOT/build-spirv-runner.sh" "$TREE" "$BUILD" "$INC" "$OUT/runner"

python3 -m gisel cases "$GISEL/tests/corpus/SPIRVLegalizerInfo.gisel" \
  --features "$GISEL/tests/cases/spirv-features.json" \
  --out "$OUT/queries.jsonl" --json
GOT=$(wc -l < "$OUT/queries.jsonl")
if [[ "$GOT" != "$EXPECTED_QUERIES" ]]; then
  echo "query set changed: $GOT lines, expected $EXPECTED_QUERIES" >&2
  exit 1
fi

python3 "$ROOT/run-queries.py" "$OUT/runner.official" \
  "$OUT/queries.jsonl" "$OUT/official.answers.jsonl"
python3 "$ROOT/run-queries.py" "$OUT/runner.ours" \
  "$OUT/queries.jsonl" "$OUT/ours.answers.jsonl"
python3 "$ROOT/diff.py" "$OUT/official.answers.jsonl" \
  "$OUT/ours.answers.jsonl" --queries "$OUT/queries.jsonl" \
  --expect-unanswerable 4 --json | tee "$OUT/diff.json"
