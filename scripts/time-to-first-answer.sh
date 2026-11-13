#!/usr/bin/env bash
# Fresh venv -> installed tools -> an answer, with a wall-clock limit.
#
# A "yes it installs" check is not enough: the first command a reader runs is
# `cases`, and the first offline gate is `suite check`.  This measures both.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LIMIT=${LIMIT:-300}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

start=$(date +%s)
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install -q --upgrade pip
"$WORK/venv/bin/pip" install -q --no-deps \
  "$ROOT" "$ROOT/../gisel" "$ROOT/../gisel-anchor"

"$WORK/venv/bin/gisel" --version
"$WORK/venv/bin/gisel" doctor
"$WORK/venv/bin/gisel" cases --corpus x86 --out "$WORK/queries.jsonl" --json \
  > "$WORK/cases.json"
test -s "$WORK/queries.jsonl"
"$WORK/venv/bin/gisel-ab" --version
"$WORK/venv/bin/gisel-ab" suite check --target x86

elapsed=$(( $(date +%s) - start ))
echo "time to first answer: ${elapsed}s (limit ${LIMIT}s)"
test "$elapsed" -lt "$LIMIT"
