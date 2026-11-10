#!/usr/bin/env bash
set -euo pipefail

# run-aarch64-domain.sh TREE BUILD INC OUT [STATE]
#
# The full AArch64 domain, per config.  `cases` asks only the points a rule
# witness justifies; `domain` asks every (opcode, types, mem, imms) the
# declared value space enumerates.  AArch64 has 9 configurations and 960,480
# points each, so the run is chunked by config: one query file, one pair of
# answer files, one diff per config, then a summed summary.
#
# Both runners answer the same file concurrently; the runner is single
# threaded per query and the two processes share nothing.
#
# The unanswerable total is part of the contract once it has been reviewed.
# Leave EXPECTED_UNANSWERABLE empty on a first run: the script then reports
# the number instead of pinning it.  CONFIGS and FORCE are overridable.
TREE=${1:?usage: run-aarch64-domain.sh TREE BUILD INC OUT [STATE]}
BUILD=${2:?}
INC=${3:?}
OUT=${4:?}
. "$(cd "$(dirname "$0")" && pwd)/env.sh"
STATE=${5:-$ROOT/.ab/aarch64-domain}
CONFIGS=${CONFIGS:-baseline small-cm fullfp16 sve bf16 cssc rcpc3 lse outline-atomics}
# 2026-11-11: the slot table now follows `class G_ATOMICRMW_OP` into its
# body, so the address slot is a pointer instead of any of the 24 types.
# Ten atomicrmw opcodes lose 2,352 invalid points per config: 960,480 to
# 936,960.
EXPECTED_PER_CONFIG=936960
EXPECTED_UNANSWERABLE=${EXPECTED_UNANSWERABLE:-39056}
EXPECTED_REF_ASSERTS=${EXPECTED_REF_ASSERTS:-1696}
EXPECTED_UNANSWERABLE_MAP=${EXPECTED_UNANSWERABLE_MAP:-}
FORCE=${FORCE:-0}
mkdir -p "$OUT" "$STATE"

"$ROOT/build-aarch64-runner.sh" "$TREE" "$BUILD" "$INC" "$OUT/runner"

{
  echo "gisel $(git -C "$GISEL" rev-parse --short HEAD)"
  echo "tree $(git -C "$TREE" rev-parse --short HEAD)"
  sha256sum "$INC" "$OUT/runner.official" "$OUT/runner.ours"
  sha256sum "$GISEL/tests/corpus/AArch64LegalizerInfo.gisel" \
    "$GISEL/tests/cases/features.json"
} | tee "$OUT/manifest.txt"

skip_done() {
  local dir=$1
  [[ "$FORCE" != 1 ]] || return 1
  [[ -f "$dir/diff.json" && -f "$dir/official.answers.jsonl" ]] || return 1
  python3 - "$dir/diff.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
ok = (d["disagree"] == 0 and d["missing_ref"] == 0
      and d["missing_ours"] == 0 and d["errors"] == 0)
sys.exit(0 if ok else 1)
PY
}

run_config() {
  local cfg=$1 dir=$OUT/$cfg started
  mkdir -p "$dir"
  if skip_done "$dir"; then
    echo "$cfg: already done, skipping (FORCE=1 to rerun)"
    return 0
  fi
  started=$(date +%s)
  python3 -m gisel domain "$GISEL/tests/corpus/AArch64LegalizerInfo.gisel" \
    --features "$GISEL/tests/cases/features.json" \
    --config "$cfg" --out "$dir/queries.jsonl" --json > "$dir/domain.json"
  local got
  got=$(wc -l < "$dir/queries.jsonl")
  if [[ "$got" != "$EXPECTED_PER_CONFIG" ]]; then
    echo "$cfg: query domain changed: $got lines, expected $EXPECTED_PER_CONFIG" >&2
    return 1
  fi

  python3 "$ROOT/run-queries.py" "$OUT/runner.official" \
    "$dir/queries.jsonl" "$dir/official.answers.jsonl" \
    --report "$dir/official.report.json" &
  local pid_official=$!
  python3 "$ROOT/run-queries.py" "$OUT/runner.ours" \
    "$dir/queries.jsonl" "$dir/ours.answers.jsonl" \
    --report "$dir/ours.report.json" &
  local pid_ours=$!
  local rc1=0 rc2=0
  wait "$pid_official" || rc1=$?
  wait "$pid_ours" || rc2=$?
  if [[ "$rc1" != 0 || "$rc2" != 0 ]]; then
    echo "$cfg: run-queries failed (official=$rc1 ours=$rc2)" >&2
    return 1
  fi

  local extra=() expect_unanswerable=$EXPECTED_UNANSWERABLE
  if [[ -n "$EXPECTED_UNANSWERABLE_MAP" ]]; then
    expect_unanswerable=$(python3 -c \
      'import json,sys; print(json.loads(sys.argv[1]).get(sys.argv[2], ""))' \
      "$EXPECTED_UNANSWERABLE_MAP" "$cfg")
  fi
  if [[ -n "$expect_unanswerable" ]]; then
    extra+=(--expect-unanswerable "$expect_unanswerable")
  fi
  if [[ -n "$EXPECTED_REF_ASSERTS" ]]; then
    extra+=(--allow-ref-asserts "$EXPECTED_REF_ASSERTS")
  fi
  # --assert-sites adds where each unanswerable query died; the comparison
  # itself still runs on status only, so this cannot change a verdict.
  if ! python3 "$ROOT/diff.py" "$dir/official.answers.jsonl" \
      "$dir/ours.answers.jsonl" --json --assert-sites "${extra[@]}" \
      | tee "$dir/diff.json"; then
    echo "$cfg: diff failed (see $dir/diff.json)" >&2
    return 1
  fi
  echo "$cfg: done in $(( $(date +%s) - started ))s"
}

failed=0
for cfg in $CONFIGS; do
  run_config "$cfg" || failed=1
done

python3 - "$OUT" $CONFIGS <<'PY'
import json, sys
from pathlib import Path

out = Path(sys.argv[1])
configs = sys.argv[2:]
rows, totals = [], {"queries": 0, "agree": 0, "disagree": 0,
                    "unanswerable": 0, "ref_asserted": 0, "errors": 0}
sites_total = {"same": 0, "mismatch": 0, "missing": 0}
sites_top, per_config_sites = {}, {}
for cfg in configs:
    d = json.load(open(out / cfg / "diff.json"))
    rows.append({"config": cfg, **{k: d[k] for k in
                 ("ref", "ours", "agree", "unanswerable", "ref_asserted",
                  "disagree", "missing_ref", "missing_ours", "errors")}})
    totals["queries"] += d["ref"]
    for k in ("agree", "disagree", "unanswerable", "ref_asserted", "errors"):
        totals[k] += d[k]
    sites = d.get("assert_sites")
    if sites:
        for key in ("same", "mismatch", "missing"):
            sites_total[key] += sites[key]
        for site, count in sites["top"]:
            sites_top[site] = sites_top.get(site, 0) + count
        per_config_sites[cfg] = {k: sites[k] for k in
                                 ("same", "mismatch", "missing")}
summary = {"target": "aarch64", "configs": len(configs), **totals,
           "per_config": rows, "assert_sites": sites_total}
(out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
if any(sites_total.values()):
    (out / "sites.json").write_text(json.dumps({
        "assert_sites": {**sites_total,
                         "top": sorted(sites_top.items(),
                                       key=lambda kv: (-kv[1], kv[0]))},
        "per_config": per_config_sites,
    }, indent=1) + "\n")
print("\nconfig      queries   agree  unanswerable  ref_assert  disagree  errors")
for r in rows:
    print("%-11s %7d %7d %13d %11d %9d %7d"
          % (r["config"], r["ref"], r["agree"], r["unanswerable"],
             r["ref_asserted"], r["disagree"], r["errors"]))
print("%-11s %7d %7d %13d %11d %9d %7d"
      % ("TOTAL", totals["queries"], totals["agree"],
         totals["unanswerable"], totals["ref_asserted"],
         totals["disagree"], totals["errors"]))
PY

if [[ "$failed" != 0 ]]; then
  echo "at least one config failed" >&2
  exit 1
fi
if [[ -z "$EXPECTED_UNANSWERABLE" && -z "$EXPECTED_UNANSWERABLE_MAP" ]]; then
  echo "unanswerable not pinned: review $OUT/summary.json, then set EXPECTED_UNANSWERABLE" >&2
fi
