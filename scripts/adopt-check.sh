#!/usr/bin/env bash
set -euo pipefail

# adopt-check.sh [TARGET...]
#
# Fetch each adoption branch from the fork and compare the committed .inc
# bytes with the gisel artifact recorded in EVIDENCE.json's adopt entries.
# AB_FORK overrides the remote; no credentials are used for public reads.

AB_ROOT=${AB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
. "$AB_ROOT/scripts/lib.sh"

targets=()
for target in "$@"; do
  targets+=(--target "$target")
done
exec python3 -m gisel_ab.evidence adopt-check \
  --manifest "$AB_ROOT/EVIDENCE.json" "${targets[@]}"
