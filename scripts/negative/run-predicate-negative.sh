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

AB_ROOT=${AB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
. "$AB_ROOT/scripts/lib.sh"
TREE=${AB_TREE:-}
BUILD=${AB_BUILD:-}
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
if ! python3 -m gisel_ab.l0.inject_predicate "$BASE_INC" "$OPCODE" "$MODE" \
    "$MUTATED_INC" --rule "$RULE" --expect "$EXPECT" >/dev/null; then
  echo "input error: could not inject $OPCODE/$MODE into $BASE_INC" >&2
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
  classify_negative_rc 0 "predicate-negative $TARGET $OPCODE" || exit $?
fi
if [[ $RC -ne 1 ]]; then
  classify_negative_rc "$RC" "predicate-negative $TARGET $OPCODE" || exit $?
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
classify_negative_rc "$RC" "predicate-negative $TARGET $OPCODE" || exit $?
