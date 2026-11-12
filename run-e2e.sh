#!/usr/bin/env bash
set -euo pipefail

# run-e2e.sh TARGET TREE BUILD INC OUT [STATE] [--print-plan]
#
# One A/B run for one target.  Every target-specific value comes from
# targets/<target>.json; the answers and diff come from ab.py, which is the
# only implementation of the two strategies.  The per-target wrappers are
# five-line shims over this script.

if [[ ${1:-} == --print-plan ]]; then
  PRINT_PLAN=1
  shift
else
  PRINT_PLAN=0
fi
TARGET=${1:?usage: run-e2e.sh TARGET TREE BUILD INC OUT [STATE]}
TREE=${2:?}
BUILD=${3:?}
INC=${4:?}
OUT=${5:?}
STATE=${6:-}
. "$(cd "$(dirname "$0")" && pwd)/env.sh"
ROOT=$(cd "$(dirname "$0")" && pwd)

if ! python3 "$ROOT/targets.py" env "$TARGET" >/dev/null 2>&1; then
  echo "unsupported target: $TARGET" >&2
  exit 2
fi
eval "$(python3 "$ROOT/targets.py" env "$TARGET")"
STATE=${STATE:-$ROOT/.ab/$TARGET}

if [[ $PRINT_PLAN -eq 1 ]]; then
  printf 'TARGET=%s\n' "$T_TARGET"
  printf 'STRATEGY=%s\n' "$T_STRATEGY"
  printf 'SOURCE=%s\n' "$T_SOURCE"
  printf 'FEATURES=%s\n' "$T_FEATURES"
  printf 'AXES=%s\n' "$T_AXES"
  printf 'BUILDER=%s\n' "$T_BUILDER"
  printf 'EXPECTED_QUERIES=%s\n' "$T_EXPECTED_QUERIES"
  printf 'ALLOW_REF_ASSERTS=%s\n' "$T_ALLOW_REF_ASSERTS"
  printf 'EXPECT_UNANSWERABLE=%s\n' "$T_EXPECT_UNANSWERABLE"
  printf 'LIB_SNAPSHOT=%s\n' "$T_LIB_SNAPSHOT"
  exit 0
fi

mkdir -p "$OUT" "$STATE"

# The aarch64 evidence keeps a copy of the library it was recorded with; it
# is an anchor, not an input to the A/B.
if [[ $T_LIB_SNAPSHOT == 1 ]]; then
  LIB=$BUILD/$T_LIBRARY
  if [[ ! -f $STATE/$(basename "$LIB") ]]; then
    cp -p "$LIB" "$STATE/$(basename "$LIB")"
    sha256sum "$LIB" > "$STATE/$(basename "$LIB").sha256"
  fi
fi

ARGS=()
if [[ -n $T_AXES ]]; then
  ARGS+=(--axes "$GISEL/$T_AXES")
fi
python3 -m gisel cases "$GISEL/$T_SOURCE" \
  --features "$GISEL/$T_FEATURES" "${ARGS[@]}" \
  --out "$OUT/queries.jsonl" --json
GOT=$(wc -l < "$OUT/queries.jsonl")
if [[ -n $T_EXPECTED_QUERIES && "$GOT" != "$T_EXPECTED_QUERIES" ]]; then
  echo "query set changed: $GOT lines, expected $T_EXPECTED_QUERIES" >&2
  exit 1
fi

# ab.py owns the strategy (swap-source / generated-ctor), the baseline, the
# pin check and the diff policy.
python3 "$ROOT/ab.py" run --target "$TARGET" --tree "$TREE" --build "$BUILD" \
  --features "$GISEL/$T_FEATURES" --queries "$OUT/queries.jsonl" \
  --out "$OUT" --state "$STATE" --inc "$INC" --no-eval --compare full
