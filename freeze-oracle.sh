#!/usr/bin/env bash
set -euo pipefail

# freeze-oracle.sh [ID...]
#
# Copy the artifacts named by EVIDENCE.json into ab/oracle/<id>/, gzipping the
# JSONL answer/query files.  verify-evidence.sh falls back to this tree when the
# original /tmp directory is gone, hashing the decompressed bytes so the
# recorded sha256 values keep their meaning.
#
# IDs are the `id` field in EVIDENCE.json (`G/x86`, `U-neg/mips`, ...).  With no
# arguments every entry is frozen.
HERE=$(cd "$(dirname "$0")" && pwd)
python3 - "$HERE" "$@" <<'PY'
import gzip
import json
import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1])
wanted = set(sys.argv[2:])
manifest = json.loads((root / "EVIDENCE.json").read_text())
dest_root = root / "oracle"
entries = [e for e in manifest["entries"] if not wanted or e["id"] in wanted]
missing = wanted - {e["id"] for e in entries}
if missing:
    raise SystemExit("unknown evidence id(s): %s" % ", ".join(sorted(missing)))

total = 0
for entry in entries:
    src = Path(entry["dir"])
    dst = dest_root / entry["id"]
    dst.mkdir(parents=True, exist_ok=True)
    for name in entry["artifacts"]:
        source = src / name
        target = dst / (name + ".gz")
        with source.open("rb") as fh, target.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as out:
                shutil.copyfileobj(fh, out)
        total += target.stat().st_size
    queries = entry.get("queries")
    if queries:
        source = Path(queries["path"])
        target = dst / "queries.jsonl.gz"
        with source.open("rb") as fh, target.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as out:
                shutil.copyfileobj(fh, out)
        total += target.stat().st_size
    print("froze %-14s %s" % (entry["id"], dst.relative_to(root)))
print("frozen %d entries, %.1f MiB" % (len(entries), total / (1 << 20)))
PY
