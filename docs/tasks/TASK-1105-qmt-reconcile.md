# TASK-1105 QMT Reconcile

Status: DONE (2026-09-06, deterministic snapshot reconciliation)

`backend/app/broker/reconcile.py` compares normalized account, order, fill and
position snapshots without mutating either side. It reports `matched` or
`mismatched` with structured missing-item and value-drift details.

`BrokerRuntime` records every reconciliation result in the local agent event
log. The current source is the mock account snapshot; a future QMT adapter can
provide the broker snapshot through the same boundary.
