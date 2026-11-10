# AB harness

This is the workbench entry point for the LLVM legalizer differential loop.
It is **not** part of gisel; the boundary is `docs/SCOPE.md`.  It consumes a
`.gisel` source (or a prebuilt `.inc`) and an answerless query JSONL, and
compares the official legalizer with one that includes the generated fragment.

## One command

```sh
python3 tools/ab/ab.py run --target x86-ctor \
  --tree /home/ubuntu/llvm/trees/explore \
  --build /home/ubuntu/llvm/builds/explore \
  --queries /tmp/x86.domain.jsonl \
  --out /tmp/ab-x86 --state /tmp/ab-state-x86 \
  --compare full
```

`tools/ab/run-x86-end-to-end.sh TREE BUILD x86.inc OUT STATE` does the same
without the ledger: official from the pinned constructor, ours after swapping
the body, then `diff.json`.

`run-g-negative.sh TARGET OPCODE OUT` is the G-side negative control:
replace one builder chain with `.unsupported()`, run the target script, and
require every disagreement to be attributed to that builder.

`--compare action` is the coarse smoke gate; `full` (default) compares
`(action, type_idx, new_type)`.  `--dry-run` validates the adapter, query file
and baseline without touching the build.  `ab.py verify` checks that the build
is back on the baseline include.

## Targets

| adapter | strategy | notes |
|---|---|---|
| `x86` | swap the constructor body for `#include` and rebuild | official is the pinned hand-written constructor |
| `x86-ctor` | generated constructor object | retired with the `.td` path; kept only for old logs |
| `aarch64` | generated constructor object | 12,583 queries; 9 configs; does not modify the build |
| `m68k` | generated constructor object | 35 queries; single `default` config |
| `ppc` | generated constructor object | 94 queries; one `default` config; 1 query asserts on both sides (upstream `bitcastIf`) |
| `riscv` | generated constructor object | 6,149 queries; 8 configs; 2 duplicate keys collapse to 6,147 |
| `wasm` | generated constructor object | 886 queries; `wasm32|wasm64` × `±sign-ext` |
| `arm` | generated constructor object | 1,614 queries; 7 configs across soft-float / VFP2 / VFP4 / NEON / V5T / hardware divide / AEABI; Thumb1 excluded (constructor registers no rule) |
| `mips` | generated constructor object | 1,656 queries; 5 configs across MSA / MIPS32r2 / unaligned access; 9 queries abort upstream (`--allow-ref-asserts 9`) |
| `spirv` | generated constructor object | 5,734 queries; 6 configs across kernel/shader × spirv32/64 × extension sets; 4 queries abort on both sides (`--expect-unanswerable 4`, upstream `changeElementSizeTo` overload) |

Adapters live in `targets/*.json`: include path, library, ninja
target, runner builder, feature table, optional axes, query-count contract.

A new target's runner is a ~30 line file: include its subtarget and legalizer
headers, alias `TargetSubtarget`/`TargetLegalizer`, include
`query_runner_common.h`, then return the config table, the target
initializers, and the legalizer constructor.  `build-query-runner.sh` derives
the include paths and the `libLLVM<TARGET>{CodeGen,Desc,Info}` list from the
target name; `build-m68k-runner.sh` is the thin per-target wrapper the adapter
names.

## Artifacts

```text
OUT/official.answers.jsonl
OUT/ours.answers.jsonl
OUT/diff.json
STATE/baseline/           baseline inc + library + provenance
STATE/ledger.jsonl        one line per run (input hashes, counts, rc)
```

Assertions do not kill the batch: the runner arms a `sigsetjmp` recovery point
around `getAction()`, writes `status:"unanswerable"` for a query that aborts,
and keeps answering (AArch64's full domain aborts 39,056 times per config).
`run-queries.py` still restarts on a real crash (SIGSEGV) and marks that query
the same way, so the answer file stays parallel to the query file.  A one-sided
assertion is a difference (`ref_asserted`), not agreement.

## Triage

`bundle.json` groups differences by `owner`:

| owner | meaning | action |
|---|---|---|
| `ours` | translation / ours assertion / evaluator | fix the rule, importer, emitter or evaluator |
| `ours-or-upstream` | rule answer differs | check the source revision before deciding |
| `llvm-or-query` | official asserts, a rule did fire | validate the query first, then record upstream |
| `query` | official asserts, no rule fired | fix the generator/axes |

A confirmed LLVM defect is recorded under
`/home/ubuntu/admin/upstream-issues/` first, per `admin/AGENTS.md` §4.1; do not
open a GitHub issue directly.

## Status

First smoke (2026-11-08): X86 400 queries, full compare, 0 disagreements;
AArch64 10,271 queries, 52 differences (45 one-sided assertions, 7 `type_idx`)
awaiting three-way attribution.  See `docs/REPORT-ab.md` §3.
