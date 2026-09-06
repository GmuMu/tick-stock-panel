# TASK-1303 Security

Status: DONE (2026-09-06)

## Scope

Add secret rotation metadata, preserve value secrecy, and constrain external
Agent capabilities.

## Evidence

- `backend/app/secrets_store.py`
- `backend/app/api/ops.py`
- `backend/app/broker/agent.py`
- `backend/app/broker/runtime.py`
- `backend/tests/test_phase13_operations.py`

Secret rotation stores only version, timestamp, and a short SHA-256
fingerprint in metadata responses; the actual secret remains in the existing
0600 local store. The standalone JSONL Agent defaults to read-only actions.
The in-process application runtime must explicitly grant mutation actions,
which keeps an external vendor boundary least-privileged by default.

## Operational boundary

This task does not enable real QMT, real market data, or real orders. The
existing Phase 12 safety gate and `TASK-1204` block remain in force.
