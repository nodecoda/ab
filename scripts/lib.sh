#!/usr/bin/env bash
# Shared roots and exit-code contract for the workbench scripts.
#
#   AB_ROOT     this checkout
#   AB_SRC      $AB_ROOT/src                (import gisel_ab without an install)
#   AB_DATA     $AB_ROOT/src/gisel_ab/data  (targets, contracts, suite, domain)
#   AB_SCRIPTS  $AB_ROOT/scripts
#   AB_CPP      $AB_ROOT/src/gisel_ab/cpp   (query runner sources)
#   GISEL       the gisel checkout that produces inc/queries (default: sibling)
#
# Every script under scripts/ sources this file.  AB_ROOT may be preset by the
# caller -- tests copy a script tree elsewhere and set it -- so nothing here
# assumes the script still sits inside the real checkout.
AB_ROOT=${AB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
AB_SRC=$AB_ROOT/src
AB_DATA=$AB_SRC/gisel_ab/data
AB_SCRIPTS=$AB_ROOT/scripts
AB_CPP=$AB_SRC/gisel_ab/cpp
GISEL=${GISEL_SRC:-$AB_ROOT/../gisel}
export AB_ROOT AB_SRC AB_DATA AB_SCRIPTS AB_CPP GISEL_SRC="$GISEL"
export PYTHONPATH="$AB_SRC:$GISEL${PYTHONPATH:+:$PYTHONPATH}"

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

# require_roots TREE BUILD
# Fail with rc=2 and an actionable message when the LLVM checkout/build are
# not given.  There is deliberately no default: a default points at the
# machine the harness was written on and can swap files in someone else's
# tree.
require_roots() {
  local tree=${1:-} build=${2:-}
  local missing=()
  [[ -n $tree ]] || missing+=("AB_TREE (or --tree DIR)")
  [[ -n $build ]] || missing+=("AB_BUILD (or --build DIR)")
  if ((${#missing[@]})); then
    echo "input error: LLVM roots not set: ${missing[*]}" >&2
    echo "  export AB_TREE=/path/to/llvm-project   # pin-compatible checkout" >&2
    echo "  export AB_BUILD=/path/to/build          # its ninja build" >&2
    return 2
  fi
  if [[ ! -d $tree/llvm/include/llvm ]]; then
    echo "input error: AB_TREE does not look like an llvm-project checkout: $tree" >&2
    return 2
  fi
  if [[ ! -f $build/build.ninja && ! -f $build/CMakeCache.txt ]]; then
    echo "input error: AB_BUILD does not look like an LLVM build: $build" >&2
    return 2
  fi
}
