# RISC-V vertical slice

Date: 2026-11-11. This is the first target where the whole stack is bound to
one snapshot: gisel emits the include and the questions, upstream-source emits
the U questions, and `ab` proves both directions on the same `riscv.inc`.

The slice is reproducible with one command:

```sh
cd /home/ubuntu/llvm/ab
python3 riscv_vertical.py \
  --tree /home/ubuntu/llvm/trees/explore \
  --build /home/ubuntu/llvm/builds/explore \
  --out /tmp/rv-vertical2
# add --l3 for a single-target check-llvm round
# rerun only the checks: python3 riscv_vertical.py --out OUT --verify-only --l3
```

The expected numbers and hashes live in `data/riscv-contract.json`; the script
fails if any of them drifts. A clean run takes 12m09s (without L3).

## Snapshot

| item | value |
|---|---|
| LLVM tree | `700e551714ccb7357a191fd41837ff1b4784abf2` |
| gisel | `de8dbbf59cf53199493f6880e435e7f0e5c53ab5` |
| pin | `9bfc850b9940` + 5 patches |
| `riscv.inc` | `fe6427bdf480143c…` |
| corpus | `3293f26167ee694b…` |
| features | `38967ab10a020b3c…` |
| llc | `ef74d1ab4964eff8…` |
| RISCV CodeGen library | `f32be744460c8155…` (baseline after restore) |

## Results

### G: gisel questions, both sides

```text
queries      6,086
agree        6,086
disagree     0
unanswerable 0
answers      byte-identical
```

### U: upstream questions, both sides

```text
queries      20,445
agree        20,445
disagree     0
unanswerable 0
answers      byte-identical
attribution  unknown_keys=0
```

### Negative controls

| direction | injection | disagree | attribution | unknown keys |
|---|---|---:|---|---:|
| G | `G_FPTOSI` builder → `.unsupported()` | 140 | `R_G_FPTOSI` 140 | 0 |
| U | `G_ADD` builder → `.unsupported()` | 152 | `G_ADD` 76 + `G_SUB` 76 | 0 |

Both controls are required: without them, `disagree=0` only means "nothing was
compared".

### Domain: 8 configurations

```text
config      queries   agree  unanswerable  ref_assert  disagree
rv64gc       253747  253747          1074           0         0
rv32gc       253747  253747          1074           0         0
rv64gcv      253747  253747          1074           0         0
rv32gcv      253747  253747          1074           0         0
rv64zbb      253747  253747           642           0         0
rv64zfh      253747  253747          1074           0         0
ristretto    253747  253747           642           0         0
rv32zilsd    253747  253747          1074           0         0
TOTAL       2029976 2029976          7728           0         0
```

The 7,728 unanswerable points are symmetric assertions (both sides abort
before returning an action); they are pinned per config, not ignored.

### MIR L1: upstream MIR replay

```text
files=181  run lines=271  in layer=270
same=270  both_abort=0  diff=0  timeout=0  out_of_layer=1
```

### MIR L2: gisel queries → minimal MIR

From the 6,086 G queries:

```text
built=4,203  unbuildable_shape=732  unbuildable_type=66  config_unrealizable=1,085
same=4,050  both_abort=151  diff=0  timeout=2  abort0_compared=2,265
```

`config_unrealizable` is entirely `ristretto`: LLVM has no equivalent
subtarget spelling, so those queries are counted, not approximated.
`both_abort` and `timeout` are pinned in `docs/REPORT-mir.md`; the former are
legalizer assertions on synthetic shapes, the latter are 3-column vector
shapes that real IR does not produce.

### L3: single-target check-llvm

```text
Total Discovered Tests: 80655
Passed:                 64916
Expectedly Failed:       146
Failed:                      0
```

The baseline round is the same tree without the replacement (0 failed); the
RISC-V round replaces only `RISCVLegalizerInfo.cpp` with the generated
include, then restores and rebuilds. The tree is clean at `700e551714cc` and
the CodeGen library is back to `f32be744…`.

## What this proves, and what it does not

Proves, for this snapshot:

- Every RISC-V G question (6,086) gets the same answer from both sides.
- Every U question (20,445) gets the same answer from both sides.
- The full declared domain (2,029,976 points) gets the same answer, including
  symmetric assertions.
- Real MIR and the whole `check-llvm` suite show no observable difference.

Does not prove:

- **U coverage still has dead rules.** `gisel-anchor/src/gisel_anchor/oracle/known-gaps/riscv.json`
  now lists 13 rules that can never become the first match. They are redundant
  clauses behind a broader earlier rule (Zfa-legal behind libcall, `{s64,s32}`
  behind `legalFor(D)`, `widenScalarIf` ordering), not missing questions. The
  16 shape gaps that the previous universe could not reach (scalable `nxv*`
  vectors, mask vectors, `slot 2 = p0`, `s128` pairs) are now witnessed in the
  V/Zfa configurations and therefore removed from the gap file.
- **L2 cannot spell every question.** 732 shapes and 66 types are not
  buildable as MIR, and `ristretto` has no LLVM subtarget spelling (1,085).
- **Two-sided agreement is not semantic correctness.** If both implementations
  are wrong in the same way, this slice will not see it.
- **L3 only shows the upstream test corpus is unchanged.** New type
  combinations are covered by G/U/domain, not by lit.

## Artifacts

`/tmp/rv-vertical3/` contains:

| path | content |
|---|---|
| `g/` | G queries, both answer files, `diff.json` |
| `u/` | U queries, both answer files, `diff.json`, `attribution.json` |
| `u-neg/` | U negative control |
| `g-neg/` | G negative control |
| `domain/` | 8 configs, per-config answers and diffs, `summary.json` |
| `l1/` | upstream MIR report and provenance |
| `l2/` | generated MIR (`mir/`) and replay report (`replay/`) |
| `l3.log` | optional single-target check-llvm log |
| `manifest.json` | hashes written by `riscv_vertical.py` |

`EVIDENCE.json` entries `G/riscv`, `U/riscv`, `U-neg/riscv`, `G-neg/riscv`
and `D/riscv` point at this run; `verify-evidence.sh` passes 39/39.
