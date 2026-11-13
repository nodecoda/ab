#!/usr/bin/env bash
set -euo pipefail

# verify-evidence.sh [DIRECTION]
#
# Re-check the recorded A/B evidence.  DIRECTION is G | G-neg | U | U-neg | D |
# MIR | closure | adopt (default: all).  VERIFY_FROZEN=1 reads only committed
# artifacts under evidence/ and src/gisel_ab/data/closure/, which is what CI
# uses.
#
# Exit codes: 0 = every selected entry passes; 1 = a shape or value failure;
# 2 = the manifest or the command line is unusable.  The per-kind rules live
# in gisel_ab/evidence.py; this file is only the stable entry point.

AB_ROOT=${AB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
. "$AB_ROOT/scripts/lib.sh"

MANIFEST=${VERIFY_MANIFEST:-$AB_ROOT/EVIDENCE.json}
args=(verify --manifest "$MANIFEST" --direction "${1:-all}")
if [[ ${VERIFY_FROZEN:-0} == 1 ]]; then
  args+=(--frozen)
fi
exec python3 -m gisel_ab.evidence "${args[@]}"
