# X86 domain: the full declared value space, both sides

This is the G-side completeness run. `cases` asks only the points a rule witness
justifies; `domain` asks every `(opcode, types, mem, imms)` the finite value
space enumerates, including combinations no rule mentions.

## Command

```sh
./run-x86-domain.sh TREE BUILD /tmp/g/x86.inc /tmp/g/x86-domain
```

The script pins two numbers. A run that changes either fails instead of
quietly absorbing a new class:

- `EXPECTED_QUERIES=95172`
- `EXPECTED_UNANSWERABLE=1414`

## Snapshot

```text
gisel    799968c
ab       754d203
pin      (trees/explore @ 700e551)
queries  sha256 923e92016d330b4a7fef66aa938334962c45d400c15c914ad787e0289dd31f45  95,172 lines
answers  sha256 c03015b5734a702d3950c2369f75bddc1277241200b3d25057cf13c57e9b940e
         official and ours are byte-identical
```

```json
{"agree": 95172, "disagree": 0, "errors": 0, "matched": 95172,
 "missing_ref": 0, "missing_ours": 0, "unanswerable": 1414, "ref_asserted": 0}
```

Domain shape: 4 configs × 113 opcodes × 24 types × 23 memory types = 95,172
points. 1,414 of them assert on both sides before returning an action.

## The 1,414 unanswerable, by opcode

Both sides raise the same assertion, so these are not disagreements; they are
the part of the declared space where neither implementation can produce an
answer. They are pinned, not ignored.

| opcode | count | why |
|---|---:|---|
| `G_CTLZ` | 288 | value type checked after result type; the declared space contains type pairs the verifier rejects |
| `G_CTPOP` | 288 | same |
| `G_CTTZ` | 288 | same |
| `G_CTTZ_ZERO_POISON` | 288 | same |
| `G_OR` | 40 | vector/scalar shape assertion |
| `G_CONSTANT_FOLD_BARRIER` | 34 | memory-shape assertion |
| `G_FREEZE` | 34 | memory-shape assertion |
| `G_IMPLICIT_DEF` | 34 | memory-shape assertion |
| `G_PHI` | 34 | memory-shape assertion |
| `G_ICMP` | 32 | result-type assertion |
| `G_FPTRUNCSTORE` | 30 | memory-shape assertion |
| `G_CONSTANT` | 22 | memory-shape assertion |
| `G_FRAME_INDEX` | 2 | memory-shape assertion |
| **total** | **1,414** | |

The four 288s are the only systematic class: the domain enumerates every type
for every slot, and these four opcodes assert on pairs the verifier forbids
before the legalizer can answer. That is a property of asking the full domain,
not a gap in the rules.

## What this does and does not prove

Proves: for every declared point that both sides can answer, the generated
`include` returns the same `(status, action, type_idx, new_type)` as the pinned
upstream constructor.

Does not prove: that the domain covers types the upstream verifier accepts but
the domain never enumerates (e.g. widths not in the type universe), nor
anything about the reverse direction (upstream rules missing from `.gisel`).
Those are the U direction and the strict-coverage numbers.
