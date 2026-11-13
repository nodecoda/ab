#!/usr/bin/env bash
set -euo pipefail

# build-ppc-runner.sh TREE BUILD INC OUT
#
# Thin per-target entry for build-query-runner.sh, so `ab.py` keeps its
# uniform `builder TREE BUILD INC PREFIX` contract.
TREE=${1:?usage: build-ppc-runner.sh TREE BUILD INC OUT}
BUILD=${2:?}
INC=${3:?}
OUT=${4:?}
AB_ROOT=${AB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
. "$AB_ROOT/scripts/lib.sh"

exec "$AB_SCRIPTS/runners/build-query-runner.sh" "$TREE" "$BUILD" "$INC" "$OUT" \
  PowerPC "$AB_CPP/ppc_query_runner.cpp" \
  "$AB_CPP/ppc_generated_ctor.cpp"
