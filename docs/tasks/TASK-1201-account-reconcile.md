# TASK-1201 Account Reconcile

Status: DONE (2026-09-06, local/mock verification)

`backend/app/services/account_reconcile.py` persists read-only account,
order, fill and position reconciliation reports under user data. Reports
include `matched`/`mismatched` status and structured value or item drift.
`/api/broker/reconcile` runs a report and `/api/broker/reconciliations`
returns its history.

The current source is the normalized Mock Broker snapshot. Real account
reconciliation remains unavailable until a separately deployed QMT Agent
provides an authenticated broker snapshot.
