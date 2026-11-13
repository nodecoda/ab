# Contributing

## The four layers

| Layer | Lives in | Contract |
|---|---|---|
| Command surface | `ab.py`, `src/gisel_ab/cli.py` | verb names and `--help`; routing only |
| L0 (rules) | `src/gisel_ab/l0/`, `src/gisel_ab/data/targets/` | `getAction()` equality, `CONTRACTS.md` §3 |
| MIR/llc | `src/gisel_ab/mir/`, `src/gisel_ab/data/mir-*.json*` | real `.mir` through `llc` |
| Shell entry points | `scripts/` | exit codes below |

New behaviour goes in a verb or a script; do not add a second entry point at
the repository root.  `ab.py` is the only `.py` allowed there.

## Exit codes

Every command that can be scripted keeps the existing contract:

- `0` success / no difference
- `1` a real difference, a failed gate, or a caught negative control
- `2` input or infrastructure error (never evidence)

Negative controls distinguish three states through
`scripts/lib.sh:classify_negative_rc`: `0` blind, `1` caught, `2` input
error.  Anything else is treated as an input error; a crash is not evidence.

## Frozen files

Do not hand-edit, reformat or regenerate:

- `EVIDENCE.json`, `VERIFICATION.json` (except adding a new cohort record)
- `evidence/**`
- `src/gisel_ab/data/suite/**` (regenerate with `ab.py suite check`, and say
  why in the commit)

`ab.py evidence verify --frozen` and `ab.py cohort check` are the checks that
notice.  A structural move changes gate fingerprints: cut a new cohort
(`-rN+1`), record it, and keep the old gate spellings in `cohort.py GATES` so
the old tag still replays.

## Run the suite

```sh
python3 -m pytest -q tests
VERIFY_FROZEN=1 ./scripts/verify-evidence.sh
python3 ab.py suite check --all
python3 ab.py doctor            # needs AB_TREE/AB_BUILD for a full pass
```

The suite needs a sibling `gisel` checkout (`GISEL_SRC` overrides it) but no
LLVM build; the tests that need a build are skipped without one.

## Commit shape

One behaviour change per commit, message `gisel-ab: <one thing>`.  A move is
its own commit (`git mv` only, no content edits), so review can see that the
bytes did not change.  Cohort commits are `ab: freeze the rN cohort`,
`ab: record the rN verification`, `ab: record the rN CI runs`.

## Adding a target

1. Add `src/gisel_ab/data/targets/<name>.json` (schema in the same folder).
2. Add a query runner under `src/gisel_ab/cpp/` and, if the target is not
   covered by the generic runner, a `scripts/runners/build-<name>-runner.sh`.
3. `ab.py refresh-counts --check` must agree; then run the e2e wrapper under
   `scripts/e2e/`.
4. Record the evidence, and only then add the target to a cohort.
