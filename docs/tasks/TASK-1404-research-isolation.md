# TASK-1404 Research Isolation

Status: DONE (2026-09-06)

Research APIs expose adapter metadata, local QuantMind artifacts, and ML
signals only. The Phase 14 regression proves that ML emission creates no
paper orders and does not enable real Broker execution. Research artifacts
are stored outside the transaction database and are included in the normal
runtime-data backup.

Evidence: `backend/tests/test_phase14_research_ml.py`.
