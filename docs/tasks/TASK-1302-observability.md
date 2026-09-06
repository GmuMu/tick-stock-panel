# TASK-1302 Observability

Status: DONE (2026-09-06)

## Scope

Make request behavior diagnosable with correlation IDs, bounded metrics, and
secret-safe logs.

## Evidence

- `backend/app/observability.py`
- `backend/app/main.py`
- `backend/app/api/ops.py`
- `backend/tests/test_phase13_operations.py`

Every HTTP request receives a validated `X-Correlation-ID` response header.
The in-memory metrics snapshot includes request totals, status codes,
bounded route counters, latency, and the last 20 server errors. Logging
handlers redact common API key, token, authorization, secret, password, and
Bearer values before output.

## Operational boundary

Metrics are process-local and intentionally not a replacement for a
multi-instance monitoring system. Restarting the service resets the counters.
