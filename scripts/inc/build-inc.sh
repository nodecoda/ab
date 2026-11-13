#!/usr/bin/env bash
# Generate the legalizer include used by the A/B build.
set -euo pipefail

AB_ROOT=${AB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
. "$AB_ROOT/scripts/lib.sh"
SOURCE=${1:-$GISEL/tests/corpus/X86LegalizerInfo.gisel}
OUT=${2:-$AB_ROOT/.ab/ours/X86LegalizerInfo.inc}
mkdir -p "$(dirname "$OUT")"
python3 -m gisel gen "$SOURCE" --emit=inc --out "$OUT"
sha256sum "$OUT"
