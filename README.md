# AB harness

This is the workbench entry point for the LLVM legalizer differential loop.
It is **not** part of gisel; the boundary is `docs/SCOPE.md`.  It consumes a
`.gisel` source (or a prebuilt `.inc`) and an answerless query JSONL, and
compares the official legalizer with one that includes the generated fragment.

## Two layers

- **L0 (`ab.py run` / `diff.py`)** compares `getAction()` for one query:
  `(opcode, types, mem, imms) -> (action, type_idx, new_type)`.
- **MIR/llc (`mir-replay.py`)** replays real `.mir` through
  `llc -run-pass=legalizer` and diffs the official and replaced libraries.

L0 is the rule-translation gate. The MIR layer is the behavior gate: it also
covers multi-step legalization, custom actions and the downstream verifier.
A pass in one is not a pass in the other; the contracts are `SCOPE.md` §3 and
§6, the report schema is `CONTRACTS.md` §8.

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

## RISC-V vertical slice

`riscv_vertical.py` is the first end-to-end target: G/U questions, both
negative controls, the 8-config domain, MIR L1/L2, and optionally L3, all
checked against `data/riscv-contract.json`.

```sh
python3 riscv_vertical.py --tree TREE --build BUILD --out /tmp/rv [--l3]
python3 riscv_vertical.py --out /tmp/rv --verify-only [--l3]
python3 riscv_vertical.py --out /tmp/rv --verify-only --frozen
```

`--frozen` rebuilds the artifact layout from the committed copies under
`oracle/` (G/U and both negative controls come from `oracle/<id>/`, the domain
summary and the two MIR reports from `oracle/riscv-vertical/`). It needs no
build tree and no `/tmp` state, so CI runs it on every push
(`.github/workflows/ci.yml`).

Evidence: `docs/EVIDENCE-riscv.md`.

## MIR/llc regression

```sh
python3 mir-replay.py --layer upstream \
  --target x86 --target aarch64 --target riscv \
  --tree /home/ubuntu/llvm/trees/explore \
  --build /home/ubuntu/llvm/builds/explore \
  --out /tmp/mir-l1 --prepare --json
```

`--prepare` snapshots the official `libLLVM<T>CodeGen.so`, applies the
generated `.inc` through `swap-source-ctor.py`, rebuilds only that library,
snapshots the replaced one, restores the source and rebuilds the baseline.
Replay then runs one `bin/llc` against both snapshots via `LD_LIBRARY_PATH`,
so the tree is never left patched while tests run.

`--negative-control OPCODE` rebuilds a mutant include with
`inject-missing-opcode.py` and requires the replay to report `diff > 0`;
otherwise the control fails and the command exits 1.

### L2: queries become MIR

```sh
python3 ab.py mir --target x86 --queries /tmp/x86.cases.jsonl \
  --tree /home/ubuntu/llvm/trees/explore \
  --build /home/ubuntu/llvm/builds/explore \
  --out /tmp/l2-x86 [--negative-control G_ADD] [--limit N] --json
```

`mir-from-query.py` turns each answerless query into a minimal `.mir` (one
`# RUN:` line each) using `data/mir-shapes.jsonc` and `data/mir-configs.json`;
queries that cannot be spelled as real MIR are counted, not dropped.  Every
def of the instruction under test gets a `COPY` sink, because the legalizer
erases trivially dead instructions before it looks at them.  Files are
preflighted with `-run-pass=none` (parse + machine verifier only), then
replayed with the same buckets as L1.  Runs that abort on both sides are
retried with `-global-isel-abort=0` so the unlegalized MIR is still compared.

`mir-config-check.py --target T --features F` checks that every gisel config
has a realizable llc spelling; `--mutate CONFIG` is its negative control.

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
