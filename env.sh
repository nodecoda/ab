#!/usr/bin/env bash
# Shared roots for the A/B harness.
#   ROOT  = this checkout (the harness)
#   GISEL = the gisel checkout that produces inc/queries (default: sibling)
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
GISEL=${GISEL_SRC:-$ROOT/../gisel}
export GISEL_SRC="$GISEL"
export PYTHONPATH="$GISEL${PYTHONPATH:+:$PYTHONPATH}"

# Negative controls share one exit-code contract:
#   0 = the mutation was not observed (blind)        -> caller returns 1
#   1 = the mutation was observed and attributed     -> caller returns 0
#   2 = input/infrastructure error, not a control    -> caller returns 2
# Anything else is treated as an input error: a crash is not evidence.
classify_negative_rc() {
  local rc=${1:?classify_negative_rc RC [LABEL]}
  local label=${2:-negative control}
  case "$rc" in
    0) echo "$label: control blind (diff agreed, mutation not observed)" >&2
       return 1 ;;
    1) echo "$label: caught" >&2
       return 0 ;;
    2) echo "$label: input error (rc=2); not counted as caught" >&2
       return 2 ;;
    *) echo "$label: unexpected rc=$rc; treated as input error" >&2
       return 2 ;;
  esac
}
