#!/usr/bin/env bash
# Shared roots for the A/B harness.
#   ROOT  = this checkout (the harness)
#   GISEL = the gisel checkout that produces inc/queries (default: sibling)
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
GISEL=${GISEL_SRC:-$ROOT/../gisel}
export GISEL_SRC="$GISEL"
export PYTHONPATH="$GISEL${PYTHONPATH:+:$PYTHONPATH}"
