# TASK-1204 Small Live

Status: PARTIAL (2026-09-06, fail-closed preflight)

## Completed

`SmallLivePreflightService` and the following endpoints now provide a
read-only technical readiness check:

- `POST /api/broker/small-live/preflight`
- `GET /api/broker/small-live/preflights`
- `POST /api/broker/small-live/activate`
- `POST /api/broker/small-live/deactivate`

The preflight checks the normalized QMT adapter status, SDK/Agent boundary,
network availability, fresh quote, fresh account snapshot, latest matched
reconciliation, Kill Switch and `HUMAN_CONFIRM` safety mode. Results are
persisted under `data/user_data/small_live_preflights.jsonl` without storing
credentials or full account snapshots.

The result is `BLOCKED` when any technical prerequisite is missing and
`READY_FOR_REVIEW` only when the technical checks pass. Both states keep
`activation_allowed=false` and `real_order_enabled=false`.

The next code boundary is now available through `QMT_AGENT_COMMAND`: the
application can launch a separately configured `qmt_vendor_agent` process
without importing `xtquant` in FastAPI. The Agent normalizes QMT connection,
quote, account, order, fill and position records. `QMT_AGENT_ALLOW_ORDERS` and
`QMT_LIVE_ORDER_ENABLED` are both required for a real order request; both
default to false. Activation additionally requires a `READY_FOR_REVIEW`
preflight and an approved, one-time `broker.enable_small_live` confirmation.
Disconnect, mode changes, Kill Switch and application restart close the
runtime activation state.

Example configuration, using the Python environment where the vendor SDK is
installed:

```dotenv
QMT_AGENT_COMMAND=["C:\\Python311\\python.exe","-m","app.broker.qmt_vendor_agent"]
QMT_USERDATA_PATH=C:\\path\\to\\qmt\\userdata
QMT_ACCOUNT_ID=your-account-id
QMT_SESSION_ID=9901
QMT_AGENT_ALLOW_ORDERS=false
QMT_LIVE_ORDER_ENABLED=false
```

The two order flags must stay false while validating read-only connection,
quote, account and reconciliation snapshots. Do not put account passwords,
tokens or local runtime data into Git.

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
