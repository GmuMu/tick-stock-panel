# TASK-1204 Small Live

Status: PARTIAL (2026-09-06, fail-closed preflight)

## Completed

`SmallLivePreflightService` and the following endpoints now provide a
read-only technical readiness check:

- `POST /api/broker/small-live/preflight`
- `GET /api/broker/small-live/preflights`

The preflight checks the normalized QMT adapter status, SDK/Agent boundary,
network availability, fresh quote, fresh account snapshot, latest matched
reconciliation, Kill Switch and `HUMAN_CONFIRM` safety mode. Results are
persisted under `data/user_data/small_live_preflights.jsonl` without storing
credentials or full account snapshots.

The result is `BLOCKED` when any technical prerequisite is missing and
`READY_FOR_REVIEW` only when the technical checks pass. Both states keep
`activation_allowed=false` and `real_order_enabled=false`.

## Still blocked

The repository cannot complete or authorize a real Small Live deployment
without external operational evidence:

- Windows QMT client and compatible `xtquant` SDK installation.
- A separately deployed and permission-reviewed QMT Agent.
- A designated test/live account and verified read-only snapshots.
- Approved single-order, daily-loss, position and symbol limits.
- Independent release approval, rollback and emergency procedures.
- A supervised acceptance run with real quotes, account, order, fill and
  reconciliation evidence.

This task must not be marked DONE based on local Mock Broker or
`LIVE_SHADOW` results. Automatic trading remains disabled.
