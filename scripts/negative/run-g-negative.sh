#!/usr/bin/env bash
set -euo pipefail

# run-g-negative.sh TARGET OPCODE OUT [--tree DIR] [--build DIR]
#
# G-side negative control: generate the include from the corpus, replace one
# opcode's builder chain with `.unsupported()`, and run the normal G end-to-end
# script against that include.  The run must disagree, and every disagreement
# must come from the rulesets built by that opcode.
#
# This reuses the target's own `run-<target>-end-to-end.sh`: the query set is
# generated from the *unmutated* corpus, so the only changed input is the
# include our side is built from.
TARGET=${1:?usage: run-g-negative.sh TARGET OPCODE OUT [--tree DIR] [--build DIR]}
OPCODE=${2:?}
OUT=${3:?}
shift 3
TREE_ARG=""
BUILD_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tree) TREE_ARG=${2:?}; shift 2 ;;
    --build) BUILD_ARG=${2:?}; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

AB_ROOT=${AB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
. "$AB_ROOT/scripts/lib.sh"
TREE=${TREE_ARG:-${AB_TREE:-}}
BUILD=${BUILD_ARG:-${AB_BUILD:-}}
require_roots "$TREE" "$BUILD" || exit 2

if ! python3 -m gisel_ab.targets env "$TARGET" >/dev/null 2>&1; then
  echo "unsupported target: $TARGET" >&2
  exit 2
fi
eval "$(python3 -m gisel_ab.targets env "$TARGET")"
CORPUS=$GISEL/$T_SOURCE
SCRIPT=$T_E2E

mkdir -p "$OUT"
BASE_INC=$OUT/base.inc
MUTATED_INC=$OUT/mutated.inc
EXPECT=$OUT/expected-rulesets.json

if ! python3 -m gisel gen "$CORPUS" --emit=inc --out "$BASE_INC" >/dev/null; then
  echo "input error: gisel gen failed for $CORPUS" >&2
  exit 2
fi
if ! python3 -m gisel_ab.l0.inject_opcode "$BASE_INC" "$OPCODE" \
    "$MUTATED_INC" --expect "$EXPECT" >/dev/null; then
  echo "input error: could not inject $OPCODE into $BASE_INC" >&2
  exit 2
fi
if [[ ! -s $MUTATED_INC || ! -s $EXPECT ]]; then
  echo "input error: missing mutated include or expectation" >&2
  exit 2
fi

set +e
"$SCRIPT" "$TREE" "$BUILD" "$MUTATED_INC" "$OUT/run" >"$OUT/run.log" 2>&1
RC=$?
set -e

# 0 = blind, 1 = caught, 2 = input error.  A crash mid-build is 1 to bash but
# has no diff.json; that is an input error, never evidence that the control
# fired.
if [[ $RC -eq 0 ]]; then
  classify_negative_rc 0 "g-negative $TARGET $OPCODE" || exit $?
fi
if [[ $RC -ne 1 ]]; then
  classify_negative_rc "$RC" "g-negative $TARGET $OPCODE" || exit $?
fi
if [[ ! -s $OUT/run/diff.json || ! -s $OUT/run/queries.jsonl ]]; then
  echo "input error: end-to-end run produced no diff (see $OUT/run.log)" >&2
  exit 2
fi

DIFF_ARGS=(--json --details 200000)
if [[ $TARGET == mips ]]; then
  DIFF_ARGS+=(--allow-ref-asserts 9)
fi
set +e
python3 -m gisel_ab.l0.diff "$OUT/run/official.answers.jsonl" \
  "$OUT/run/ours.answers.jsonl" --queries "$OUT/run/queries.jsonl" \
  "${DIFF_ARGS[@]}" > "$OUT/run/diff.json"
DIFF_RC=$?
set -e
if [[ $DIFF_RC -ne 1 ]]; then
  echo "input error: re-diff rc=$DIFF_RC, expected 1" >&2
  exit 2
fi

set +e
python3 -m gisel_ab.l0.g_attribution "$OUT/run/diff.json" "$OUT/run/queries.jsonl" \
  "$EXPECT" "$OUT/run/attribution.json"
ATTR_RC=$?
set -e
if [[ $ATTR_RC -eq 2 ]]; then
  echo "input error: attribution could not read its inputs" >&2
  exit 2
fi
if [[ $ATTR_RC -ne 0 ]]; then
  echo "negative control: disagreements were not attributed to $OPCODE" >&2
  exit 1
fi
classify_negative_rc "$RC" "g-negative $TARGET $OPCODE" || exit $?
