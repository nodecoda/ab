#!/usr/bin/env bash
set -euo pipefail

# run-domain.sh TARGET TREE BUILD INC OUT [STATE]
#
# The full domain of one generated-constructor adapter: every
# (opcode, types, mem, imms) the declared value space enumerates, per config,
# answered by both runners and diffed.  `cases` asks only the points a rule
# witness justifies; this asks the whole declared space.
#
# x86, aarch64 and riscv keep their own scripts: x86 rebuilds a shipping
# runner, aarch64 and riscv pin per-config unanswerable maps that predate this
# entry point.  This script is the uniform path for the other adapters, and it
# reads its contract from data/domain.json:
#
#   {"targets": {"<target>": {"configs": {"<cfg>": <queries>},
#                             "unanswerable": {"<cfg>": <n>},
#                             "ref_asserts": {"<cfg>": <n>},
#                             "assert_sites": {"<cfg>": "<site>=<n>,..."}}}}
#
# A missing target section means first run: the script reports the measured
# numbers, writes them to <OUT>/first-run.json and exits 0 without pinning.
# Review that file, copy the numbers into data/domain.json, rerun.
AB_ROOT=${AB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
. "$AB_ROOT/scripts/lib.sh"

TARGET=${1:?usage: run-domain.sh TARGET TREE BUILD INC OUT [STATE]}
if [[ ${2:-} == --plan ]]; then
  exec python3 -m gisel_ab.domain_plan "$TARGET"
fi
case "$TARGET" in
  x86|aarch64|riscv)
    shift
    exec "$AB_SCRIPTS/domain/run-$TARGET-domain.sh" "$@"
    ;;
esac
TREE=${2:?}
BUILD=${3:?}
INC=${4:?}
OUT=${5:?}
STATE=${6:-$AB_ROOT/.ab/$TARGET-domain}
SPEC=$AB_DATA/targets/$TARGET.json
CONTRACT=$AB_DATA/domain.json
FORCE=${FORCE:-0}

read -r SOURCE FEATURES BUILDER < <(python3 - "$SPEC" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print(d["source"], d["features"], d["runner"]["builder"])
PY
)
SOURCE=$GISEL/$SOURCE
FEATURES=$GISEL/$FEATURES
CONFIGS=${CONFIGS:-$(python3 -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))))' "$FEATURES")}

mkdir -p "$OUT" "$STATE"

"$AB_SCRIPTS/runners/$BUILDER" "$TREE" "$BUILD" "$INC" "$OUT/runner"

{
  echo "gisel $(git -C "$GISEL" rev-parse --short HEAD)"
  echo "tree $(git -C "$TREE" rev-parse --short HEAD)"
  sha256sum "$INC" "$OUT/runner.official" "$OUT/runner.ours"
  sha256sum "$SOURCE" "$FEATURES"
} | tee "$OUT/manifest.txt"

contract() {
  # contract <field> <config>: print the pinned value, or nothing.
  python3 - "$CONTRACT" "$TARGET" "$1" "$2" <<'PY'
import json, sys
path, target, field, cfg = sys.argv[1:5]
try:
    d = json.load(open(path))["targets"].get(target)
except (OSError, KeyError):
    d = None
if d is None:
    sys.exit(0)
value = (d.get(field) or {}).get(cfg)
if value is None:
    sys.exit(0)
print(value if not isinstance(value, dict) else json.dumps(value))
PY
}

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
  local cfg=$1
  local dir=$OUT/$cfg
  local started
  mkdir -p "$dir"
  if skip_done "$dir"; then
    echo "$cfg: already done, skipping (FORCE=1 to rerun)"
    return 0
  fi
  started=$(date +%s)
  python3 -m gisel domain "$SOURCE" --features "$FEATURES" \
    --config "$cfg" --out "$dir/queries.jsonl" --json > "$dir/domain.json"
  local got expect
  got=$(wc -l < "$dir/queries.jsonl")
  expect=$(contract configs "$cfg")
  if [[ -n "$expect" && "$got" != "$expect" ]]; then
    echo "$cfg: query domain changed: $got lines, expected $expect" >&2
    return 1
  fi

  python3 -m gisel_ab.l0.queries "$OUT/runner.official" \
    "$dir/queries.jsonl" "$dir/official.answers.jsonl" \
    --report "$dir/official.report.json" &
  local pid_official=$!
  python3 -m gisel_ab.l0.queries "$OUT/runner.ours" \
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

  # `unanswerable` is the symmetric count (both sides assert) and goes to
  # --expect-unanswerable; `ref_asserts` is the single-sided count and goes to
  # --allow-ref-asserts.  `assert_sites` only names where they died, for the
  # reader and for EVIDENCE; passing it as --allow-ref-asserts would demand
  # single-sided asserts that do not exist.
  local extra=() unans asserts
  unans=$(contract unanswerable "$cfg")
  asserts=$(contract ref_asserts "$cfg")
  if [[ -n "$asserts" && "$asserts" != 0 ]]; then
    extra+=(--allow-ref-asserts "$asserts")
  fi
  if [[ -n "$unans" ]]; then
    extra+=(--expect-unanswerable "$unans")
  fi
  if ! python3 -m gisel_ab.l0.diff "$dir/official.answers.jsonl" \
      "$dir/ours.answers.jsonl" --queries "$dir/queries.jsonl" \
      --json --assert-sites "${extra[@]}" \
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

python3 - "$OUT" "$TARGET" $CONFIGS <<'PY'
import json, sys
from pathlib import Path

out, target = Path(sys.argv[1]), sys.argv[2]
configs = sys.argv[3:]
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
summary = {"target": target, "configs": len(configs), **totals,
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
