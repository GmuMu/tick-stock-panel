# TASK-0003 Baseline Test Harness

## Task

- Branch: `audit/0002-reachability`
- Start SHA: `25e5680`
- End SHA: working tree (not committed, 2026-09-04)
- Scope: add a small offline smoke surface for the primary application boundaries.

## Implementation

Added `backend/tests/test_baseline_harness.py` with deterministic coverage for:

- fuyao snapshot mapping and canonical unit conversion;
- indicator pipeline output;
- strategy discovery and execution;
- close-price backtest matching;
- monitor event evaluation and cooldown;
- FastAPI health and OpenAPI smoke endpoints.

The harness uses synthetic rows and temporary strategy files. It does not read
or write runtime credentials, call external APIs, or depend on `data/` contents.

## Verification

- Targeted fuyao regression: `78 passed`
- Baseline harness and affected regression tests: `130 passed`
- New harness Ruff check: passed
- Ruff: existing `RUF012` findings remain in the pre-existing provider class
  field maps; no unrelated cleanup was included.
- `git diff --check`: passed

## Acceptance

- AC result: `PASS`
- Known risk: full-project Ruff still contains baseline findings recorded in
  `docs/audit/BASELINE_FREEZE.md`; this task does not claim to clean them up.
- Next task ready: `YES` for `TASK-0004` review, subject to final verification.
