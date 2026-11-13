# Changelog

This file records shape changes to the workbench, not results.  Counts,
commits and gate outcomes live in `RELEASE.json` and `VERIFICATION.json`,
which are generated and must not be hand-edited.

## Unreleased — productization (cohorts r8, r9)

- One entry point: `python3 ab.py <verb>` (or `gisel-ab` after
  `pip install .`).  The verb table is `doctor run mir verify diff l3 suite
  vertical cohort evidence plan`; the old per-script entry points are gone.
- One package: every module moved under `src/gisel_ab/` (`l0/` for the
  answer/diff layer, `mir/` for the MIR layer).  Flat imports and the
  `sys.path` shims that made them work are gone; `tests/conftest.py` keeps
  the old names only as test aliases.
- Shell entry points moved under `scripts/` (`runners/`, `domain/`, `e2e/`,
  `negative/`, `inc/`).  `scripts/lib.sh` is the one place that defines the
  roots and the negative-control exit-code contract.
- C++ query runners moved to `src/gisel_ab/cpp/`; the target registry, the
  contracts, the domain table and the offline suite snapshots moved to
  `src/gisel_ab/data/`.
- The frozen evidence tree moved from `oracle/` to `evidence/`.  Contents and
  hashes are unchanged; `EVIDENCE.json` is byte-identical.
- Packaging: `pyproject.toml` (src layout, `gisel-ab` console script, no
  third-party dependencies) and `MANIFEST.in`.  The wheel carries code, the
  target registry, the suite snapshots and the C++ sources; the 102 MB
  evidence tree is repository-only.
- CI gains a packaging job (install the wheel, run `--help` and the offline
  suite, assert `evidence/` is absent) and a cohort check job.
- `cohort check` treats a record that names an older cohort as "not written
  yet" (rc=0, one line saying so) instead of drift.  The record commit is a
  child of the tag, so at the tag the manifest is already the new cohort while
  `VERIFICATION.json` still names the previous one.  `--worktree` keeps
  failing in that state: a drift check needs a record for this cohort.
  `r9` is the cohort that carries this fix and the refreshed anchor pin; its
  evidence tree is byte-identical to `r8`.

## Earlier

See the git history for r1–r7.  Each cohort's gates and commits are in
`RELEASE.json`; the recorded verification of each tag is in
`VERIFICATION.json`.
