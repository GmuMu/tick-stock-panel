# TASK-0901 Unified Signal

Status: DONE (2026-09-06)

`backend/app/strategy/unified_signal.py` defines the versioned `UnifiedSignal`
contract and adapters for strategy candidates and monitor events. The adapter
adds deterministic identity, source, kind, action and provenance without
rewriting producer semantics. Signals are persisted in the transaction SQLite
store and exposed through `/api/paper-trading/signals`.

Evidence: `tests/test_phase9_phase10_paper_loop.py` covers deterministic IDs and
idempotent persistence.
