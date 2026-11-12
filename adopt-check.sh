#!/usr/bin/env bash
set -euo pipefail

# adopt-check.sh [TARGET...]
#
# Fetch each adoption branch from the fork and compare the committed .inc
# bytes with the gisel artifact recorded in EVIDENCE.json's adopt entries.
# AB_FORK overrides the remote; no credentials are used for public reads.

HERE=$(cd "$(dirname "$0")" && pwd)
targets=()
for target in "$@"; do
  targets+=(--target "$target")
done
exec python3 "$HERE/evidence.py" adopt-check --manifest "$HERE/EVIDENCE.json" \
  "${targets[@]}"
