#!/usr/bin/env bash
set -euo pipefail

# verify-evidence.sh [DIRECTION]
#
# Re-check the recorded A/B evidence.  DIRECTION is G | G-neg | U | U-neg | D |
# MIR | closure | adopt (default: all).  VERIFY_FROZEN=1 reads only committed
# artifacts under oracle/ and data/closure/, which is what CI uses.
#
# Exit codes: 0 = every selected entry passes; 1 = a shape or value failure;
# 2 = the manifest or the command line is unusable.  The per-kind rules live
# in evidence.py; this file is only the stable entry point.

HERE=$(cd "$(dirname "$0")" && pwd)
MANIFEST=${VERIFY_MANIFEST:-$HERE/EVIDENCE.json}
export AB_HOME=$HERE

args=(verify --manifest "$MANIFEST" --direction "${1:-all}")
if [[ ${VERIFY_FROZEN:-0} == 1 ]]; then
  args+=(--frozen)
fi
exec python3 "$HERE/evidence.py" "${args[@]}"
