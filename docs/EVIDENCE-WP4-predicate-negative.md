# Predicate-level negative controls, nine targets

The G-side control in `EVIDENCE-WP4-G-negative-control.md` replaces a whole
opcode builder with `.unsupported()`.  That proves the diff notices a missing
ruleset; it does not prove it notices a **wrong predicate** on a ruleset that is
still present.  This round adds two predicate mutations:

- **widen**: drop one top-level `&&` conjunct of a rule predicate (or make it
  `true` when there is no conjunct), so the rule matches strictly more queries;
- **narrow**: append `&& false`, so the rule matches nothing.

Both are applied to the generated include, not to the `.gisel` corpus: the query
set is still generated from the unmutated source, so the only changed input is
our side's compiled rules.

## Command

```sh
ab/run-predicate-negative.sh TARGET OPCODE MODE OUT [RULE]
# RULE defaults to -1: the first predicate that is not literally `true`
```

`G_LOAD` is used where its builder is unique; RISC-V and AArch64 build `G_LOAD`
several times (address spaces), so those two use `G_ADD`.  M68k's `G_ADD` has no
non-trivial predicate, so it uses `G_LOAD` as well.

## Snapshot

```text
gisel  799968c + the target-seed change in this round
ab     (this tree)
tree   700e551
```

## Results

Every row: the diff disagreed (`rc=1`), every disagreement was attributed to
the injected opcode's own ruleset, and `outside_expected`/`unknown_keys` are 0.

| target | opcode | widen | ruleset | narrow | ruleset |
|---|---|---:|---|---:|---|
| X86 | `G_LOAD` | 71 | `X_G_LOAD` | 16 | `X_G_LOAD` |
| AArch64 | `G_ADD` | 68 | `A_G_ADD` | 20 | `A_G_ADD` |
| RISC-V | `G_ADD` | 10 | `R_G_ADD` | 3 | `R_G_ADD` |
| ARM | `G_LOAD` | 39 | `A_G_LOAD` | 28 | `A_G_LOAD` |
| Mips | `G_LOAD` | 117 | `Mips_G_LOAD` | 20 | `Mips_G_LOAD` |
| PowerPC | `G_LOAD` | 4 | `P_G_LOAD` | 2 | `P_G_LOAD` |
| M68k | `G_LOAD` | 8 | `M68k_G_STORE` | 4 | `M68k_G_STORE` |
| WebAssembly | `G_LOAD` | 36 | `Wasm_G_LOAD` | 16 | `Wasm_G_LOAD` |
| SPIR-V | — | — | — | — | — |

SPIR-V is not covered: `run-spirv-end-to-end.sh` takes 5m41s for 5,734 queries
before any mutation, so the two controls are deferred with the same status as
the graph (P1-2 / P4 in the plan).  This is recorded as uncovered, not as zero.

## What the numbers say

- A **widened** predicate produces more disagreements than a narrowed one on
  every target: making one legal rule unconditional changes the answer for
  every query it now captures, while disabling one rule only changes the
  queries that had no later answer.
- The attribution is exact: all disagreements land in the mutated opcode's
  ruleset, including M68k where `G_LOAD` and `G_STORE` share
  `M68k_G_STORE`.
- The counts are not comparable across targets: they scale with the query set
  (X86 3,027 vs M68k 35) and with how many queries the chosen rule owns.

## A join bug this control found

The first X86 run reported 71 disagreements but `g-attribution.py` could only
place 8; 63 keys were "not in the query file".  The cause was a type-model
mismatch, not a rule difference:

```text
queries.jsonl   types ["s16", "p0:*"]      (width decided by config)
answers.jsonl   types ["s16", "p0:32"]     (runner echoes the real width)
```

`u-attribution.query_key` joined on the literal spelling, so every query with
a wildcard pointer was lost.  The baseline had no disagreements on those
queries, so the bug was invisible until a widened predicate made them differ.
Fix: `_expand_pointer_widths` duplicates a wildcard key for 32 and 64; both
`load_queries` and `g-attribution.py` use it.  The control would have looked
like an attribution failure (63 unknown keys) rather than a pass.

## Verification

```sh
cd /home/ubuntu/llvm/ab && python3 -m pytest -q tests
# 40 passed, 5 subtests
```
