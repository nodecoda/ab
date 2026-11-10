#!/usr/bin/env bash
set -euo pipefail

# build-mips-runner.sh TREE BUILD INC OUT
#
# Thin per-target entry for build-query-runner.sh, so `ab.py` keeps its
# uniform `builder TREE BUILD INC PREFIX` contract.
TREE=${1:?usage: build-mips-runner.sh TREE BUILD INC OUT}
BUILD=${2:?}
INC=${3:?}
OUT=${4:?}
. "$(cd "$(dirname "$0")" && pwd)/env.sh"

exec "$ROOT/build-query-runner.sh" "$TREE" "$BUILD" "$INC" "$OUT" \
  Mips "$ROOT/mips_query_runner.cpp" \
  "$ROOT/mips_generated_ctor.cpp"
