# gisel-ab docs: index

Start with [the README](../README.md).  This page is the "what do I read next"
map; every entry names the question it answers.

## First run

| Question | Document |
|---|---|
| Show me the whole loop on a small target | [TUTORIAL-m68k.md](TUTORIAL-m68k.md) |
| Which layer answers which question, and what does green prove? | [QUICKSTART-with-llvm.md](QUICKSTART-with-llvm.md) |
| Where is the boundary between gisel and this workbench? | [../SCOPE.md](../SCOPE.md) |
| What is a report's JSON shape? | [../CONTRACTS.md](../CONTRACTS.md) |

## Reproducing evidence

| Question | Document |
|---|---|
| Replay the frozen artifacts without a build | [REPLAY-FROZEN.md](REPLAY-FROZEN.md) |
| What did the domain runs measure? | [EVIDENCE-domain.md](EVIDENCE-domain.md) |
| What did the U direction measure? | [EVIDENCE-U.md](EVIDENCE-U.md) |
| RISC-V slice | [EVIDENCE-riscv.md](EVIDENCE-riscv.md) |
| G-side negative control | [EVIDENCE-WP4-G-negative-control.md](EVIDENCE-WP4-G-negative-control.md) |
| Predicate negative control | [EVIDENCE-WP4-predicate-negative.md](EVIDENCE-WP4-predicate-negative.md) |
| Multi-step closure | [CLOSURE.md](CLOSURE.md) |

## Design and history

| Question | Document |
|---|---|
| Why is the harness shaped this way? | [REPORT-ab.md](REPORT-ab.md) |
| What does the MIR layer do and not do? | [REPORT-mir.md](REPORT-mir.md) |
| Requirements this workbench answers | [REQUIREMENTS-ab.md](REQUIREMENTS-ab.md) |
| What is still open | [GAPS.md](GAPS.md), [BACKLOG.md](BACKLOG.md) |
| How the official baseline was cut | [OFFICIAL-BASE.md](OFFICIAL-BASE.md) |
| Adoption branches and rollback | [ADOPT.md](ADOPT.md) |

## Evidence tree

`evidence/` is frozen output, not input.  Do not hand-edit it: `ab.py
evidence verify --frozen` recomputes every hash, and `ab.py cohort check`
fails when a tracked file changes without a new cohort.  The tree is not part
of the wheel or the sdist.
