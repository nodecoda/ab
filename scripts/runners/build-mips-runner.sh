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
AB_ROOT=${AB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
. "$AB_ROOT/scripts/lib.sh"

exec "$AB_SCRIPTS/runners/build-query-runner.sh" "$TREE" "$BUILD" "$INC" "$OUT" \
  Mips "$AB_CPP/mips_query_runner.cpp" \
  "$AB_CPP/mips_generated_ctor.cpp"
