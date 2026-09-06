# TASK-1001 Risk Contract

Status: DONE (2026-09-06)

`backend/app/services/risk_engine.py` defines versioned `RiskDecision` output:
passed/rejected status, structured reason codes, input snapshot, contract
version and rules version. A missing or non-FRESH data quality result is
fail-closed. Risk checks are persisted and audited before a paper order can be
accepted.
