#!/usr/bin/env bash
# Run both answerers on one fixed query file and compare the complete streams.
#
#   run.sh QUERIES [OUT] [REFERENCE_RUNNER] [OURS_RUNNER]
set -euo pipefail

AB_ROOT=${AB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
. "$AB_ROOT/scripts/lib.sh"
QUERIES=${1:?usage: run.sh QUERIES [OUT] [REFERENCE_RUNNER] [OURS_RUNNER]}
OUT=${2:-$AB_ROOT/.ab/results}
REF=${3:-${AB_REFERENCE_RUNNER:-$AB_ROOT/.ab/runner.reference}}
OURS=${4:-${AB_OURS_RUNNER:-$AB_ROOT/.ab/runner.shipping}}
mkdir -p "$OUT"
"$REF" --queries "$QUERIES" > "$OUT/reference.answers.jsonl"
"$OURS" --queries "$QUERIES" > "$OUT/ours.answers.jsonl"
python3 -m gisel_ab.l0.diff "$OUT/reference.answers.jsonl" \
  "$OUT/ours.answers.jsonl" --queries "$QUERIES" --json | tee "$OUT/diff.json"
