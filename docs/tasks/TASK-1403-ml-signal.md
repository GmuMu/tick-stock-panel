# TASK-1403 ML Signal

Status: DONE (2026-09-06)

`backend/app/research/ml_signal.py` maps model output to the existing
versioned `UnifiedSignal` contract with `source="ml"` and
`research_only=true` provenance. Signals are persisted through the existing
transaction store, but the adapter has no order, risk bypass, or Broker
capability.

Evidence: `backend/tests/test_phase14_research_ml.py`.
