#!/usr/bin/env bash
set -euo pipefail

# run-x86-domain.sh TREE BUILD INC OUT [STATE]
#
# The full X86 domain, not the compressed `cases` set: both runners answer
# every query `gisel domain` enumerates.  This is the G-side completeness
# check; `cases` only asks the points a rule witness justifies.
#
# The unanswerable count is part of the contract.  It is dominated by four
# opcodes whose result type is checked before the value type (G_CTLZ, G_CTPOP,
# G_CTTZ, G_CTTZ_ZERO_POISON, 288 assertions each on the four configs) plus a
# tail of memory-shape asserts.  A new class of assertion moves the count and
# must be reviewed, not absorbed.
TREE=${1:?usage: run-x86-domain.sh TREE BUILD INC OUT [STATE]}
BUILD=${2:?}
INC=${3:?}
OUT=${4:?}
. "$(cd "$(dirname "$0")" && pwd)/env.sh"
STATE=${5:-$ROOT/.ab/x86-domain}
EXPECTED_QUERIES=91340
EXPECTED_UNANSWERABLE=1418
mkdir -p "$OUT" "$STATE"

restore() {
  python3 "$ROOT/swap-source-ctor.py" restore \
    --target x86 --tree "$TREE" >/dev/null 2>&1 || true
}
cleanup() {
  rc=$?
  restore
  ninja -C "$BUILD" libLLVMX86CodeGen.so >/dev/null 2>&1 || true
  exit "$rc"
}
trap cleanup EXIT

restore
ninja -C "$BUILD" libLLVMX86CodeGen.so

python3 -m gisel domain "$GISEL/tests/corpus/X86LegalizerInfo.gisel" \
  --features "$GISEL/tests/cases/x86-features.json" \
  --out "$OUT/queries.jsonl" --json
GOT=$(wc -l < "$OUT/queries.jsonl")
if [[ "$GOT" != "$EXPECTED_QUERIES" ]]; then
  echo "query domain changed: $GOT lines, expected $EXPECTED_QUERIES" >&2
  exit 1
fi

"$ROOT/build-runner.sh" "$TREE" "$BUILD" "$OUT/runner.official" shipping
python3 "$ROOT/run-queries.py" "$OUT/runner.official" \
  "$OUT/queries.jsonl" "$OUT/official.answers.jsonl" \
  --report "$OUT/official.report.json"

python3 "$ROOT/swap-source-ctor.py" apply \
  --target x86 --tree "$TREE" --inc "$INC"
ninja -C "$BUILD" libLLVMX86CodeGen.so
"$ROOT/build-runner.sh" "$TREE" "$BUILD" "$OUT/runner.ours" shipping
python3 "$ROOT/run-queries.py" "$OUT/runner.ours" \
  "$OUT/queries.jsonl" "$OUT/ours.answers.jsonl" \
  --report "$OUT/ours.report.json"

python3 "$ROOT/diff.py" "$OUT/official.answers.jsonl" \
  "$OUT/ours.answers.jsonl" --json \
  --expect-unanswerable "$EXPECTED_UNANSWERABLE" | tee "$OUT/diff.json"
