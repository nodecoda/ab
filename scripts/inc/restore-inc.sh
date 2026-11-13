#!/usr/bin/env bash
set -euo pipefail

BUILD=${1:?usage: restore-inc.sh BUILD [STATE]}
AB_ROOT=${AB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
. "$AB_ROOT/scripts/lib.sh"
STATE=${2:-$AB_ROOT/.ab}
TREE=${LLVM_TREE:-$(cd "$BUILD/../../trees/$(basename "$BUILD")" && pwd)}
BASE=$STATE/baseline/X86LegalizerInfo.inc
TARGET=$BUILD/lib/Target/X86/X86LegalizerInfo.inc
test -f "$BASE"
cp -p "$BASE" "$TARGET"
touch "$TREE/llvm/lib/Target/X86/GISel/X86LegalizerInfo.cpp"
ninja -C "$BUILD" libLLVMX86CodeGen.so
echo "restored $TARGET"
