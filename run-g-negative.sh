#!/usr/bin/env bash
set -euo pipefail

# run-g-negative.sh TARGET OPCODE OUT
#
# G-side negative control: generate the include from the corpus, replace one
# opcode's builder chain with `.unsupported()`, and run the normal G end-to-end
# script against that include.  The run must disagree, and every disagreement
# must come from the rulesets built by that opcode.
#
# This reuses the target's own `run-<target>-end-to-end.sh`: the query set is
# generated from the *unmutated* corpus, so the only changed input is the
# include our side is built from.
TARGET=${1:?usage: run-g-negative.sh TARGET OPCODE OUT}
OPCODE=${2:?}
OUT=${3:?}

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
python3 "$PWD/inject-missing-opcode.py" "$BASE_INC" "$OPCODE" \
  "$MUTATED_INC" --expect "$EXPECT" >/dev/null

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
  echo "negative control: diff agreed, injection was not observed" >&2
  exit 1
fi
echo "g-negative $TARGET $OPCODE: rc=$RC disagreed as expected" >&2
