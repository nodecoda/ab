#!/usr/bin/env bash
# Generate the legalizer include used by the A/B build.
set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/env.sh"
SOURCE=${1:-$GISEL/tests/corpus/X86LegalizerInfo.gisel}
OUT=${2:-$ROOT/.ab/ours/X86LegalizerInfo.inc}
mkdir -p "$(dirname "$OUT")"
python3 -m gisel gen "$SOURCE" --emit=inc --out "$OUT"
sha256sum "$OUT"
