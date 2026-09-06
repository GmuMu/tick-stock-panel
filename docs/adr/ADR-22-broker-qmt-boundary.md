# ADR-22: Broker and QMT Boundary

## Status

Accepted, 2026-09-06.

## Decision

Phase 11 introduces a vendor-neutral Broker Protocol and a process-capable
QMT Agent Core. The application talks to normalized quote, order, fill,
account and reconciliation records. The checked-in implementation is a
deterministic Mock Broker only.

QMT integration is isolated behind the Agent boundary. The current repository
does not import a QMT SDK, make network calls, or place real orders. The
execution policy defaults to `HUMAN_CONFIRM`, permits `LIVE_SHADOW` only for
mock state, and rejects `AUTO`.

## Consequences

- Quote records carry explicit `quality` and `provenance` and unavailable data
  is not treated as fresh.
- Reconciliation is a read-only comparison and cannot silently mutate OMS or
  position state.
- Kill Switch, disconnect and missing human confirmation fail closed.
- A future Windows QMT worker can implement the protocol without coupling the
  FastAPI application to vendor-specific objects.
