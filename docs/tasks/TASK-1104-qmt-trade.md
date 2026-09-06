# TASK-1104 QMT Trade

Status: DONE (2026-09-06, HUMAN_CONFIRM/LIVE_SHADOW mock boundary)

`backend/app/broker/adapters.py::QmtTradeAdapter` routes normalized order
requests through the safety controller and isolated agent. HUMAN_CONFIRM
requires an explicit confirmation flag; LIVE_SHADOW writes only to the mock
ledger. Duplicate client order IDs are replayed by the mock adapter.

AUTO is rejected, and selecting the unconfigured QMT adapter never submits an
order. Real broker side effects are disabled by construction.
