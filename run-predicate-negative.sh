#!/usr/bin/env bash
set -euo pipefail

# run-predicate-negative.sh TARGET OPCODE MODE OUT [RULE]
#
# Predicate-level negative control: keep the opcode's builder chain, but widen
# one rule predicate (drop a top-level conjunct / make it true) or narrow it
# (append `&& false`).  The rest of the run is the normal G end-to-end: the
# query set comes from the unmutated corpus, so the only changed input is the
# include our side is built from.
#
# RULE defaults to -1: the first predicate that is not literally `true`.
TARGET=${1:?usage: run-predicate-negative.sh TARGET OPCODE MODE OUT [RULE]}
OPCODE=${2:?}
MODE=${3:?}
OUT=${4:?}
RULE=${5:--1}

. "$(cd "$(dirname "$0")" && pwd)/env.sh"
TREE=${AB_TREE:-/home/ubuntu/llvm/trees/explore}
BUILD=${AB_BUILD:-/home/ubuntu/llvm/builds/explore}

case "$TARGET" in
  x86)     CORPUS=$GISEL/tests/corpus/X86LegalizerInfo.gisel
           SCRIPT=$PWD/run-x86-end-to-end.sh ;;
  aarch64) CORPUS=$GISEL/tests/corpus/AArch64LegalizerInfo.gisel
           SCRIPT=$PWD/run-aarch64-end-to-end.sh ;;
  riscv)   CORPUS=$GISEL/tests/corpus/RISCVLegalizerInfo.gisel
           SCRIPT=$PWD/run-riscv-end-to-end.sh ;;
  arm)     CORPUS=$GISEL/tests/corpus/ARMLegalizerInfo.gisel
           SCRIPT=$PWD/run-arm-end-to-end.sh ;;
  mips)    CORPUS=$GISEL/tests/corpus/MipsLegalizerInfo.gisel
           SCRIPT=$PWD/run-mips-end-to-end.sh ;;
  ppc)     CORPUS=$GISEL/tests/corpus/PowerPCLegalizerInfo.gisel
           SCRIPT=$PWD/run-ppc-end-to-end.sh ;;
  m68k)    CORPUS=$GISEL/tests/corpus/M68kLegalizerInfo.gisel
           SCRIPT=$PWD/run-m68k-end-to-end.sh ;;
  wasm)    CORPUS=$GISEL/tests/corpus/WebAssemblyLegalizerInfo.gisel
           SCRIPT=$PWD/run-wasm-end-to-end.sh ;;
  spirv)   CORPUS=$GISEL/tests/corpus/SPIRVLegalizerInfo.gisel
           SCRIPT=$PWD/run-spirv-end-to-end.sh ;;
  *) echo "unsupported target: $TARGET" >&2; exit 2 ;;
esac

mkdir -p "$OUT"
BASE_INC=$OUT/base.inc
MUTATED_INC=$OUT/mutated.inc
EXPECT=$OUT/expected-rulesets.json

python3 -m gisel gen "$CORPUS" --emit=inc --out "$BASE_INC" >/dev/null
python3 "$PWD/inject-predicate.py" "$BASE_INC" "$OPCODE" "$MODE" \
  "$MUTATED_INC" --rule "$RULE" --expect "$EXPECT" >/dev/null

set +e
"$SCRIPT" "$TREE" "$BUILD" "$MUTATED_INC" "$OUT/run" >"$OUT/run.log" 2>&1
RC=$?
set -e

DIFF_ARGS=(--json --details 200000)
if [[ $TARGET == mips ]]; then
  DIFF_ARGS+=(--allow-ref-asserts 9)
fi
set +e
python3 "$PWD/diff.py" "$OUT/run/official.answers.jsonl" \
  "$OUT/run/ours.answers.jsonl" "${DIFF_ARGS[@]}" > "$OUT/run/diff.json"
set -e

python3 "$PWD/g-attribution.py" "$OUT/run/diff.json" "$OUT/run/queries.jsonl" \
  "$EXPECT" "$OUT/run/attribution.json"

if [[ $RC -eq 0 ]]; then
  echo "negative control: diff agreed, predicate injection was not observed" >&2
  exit 1
fi
echo "predicate-negative $TARGET $OPCODE $MODE: rc=$RC disagreed as expected" >&2
