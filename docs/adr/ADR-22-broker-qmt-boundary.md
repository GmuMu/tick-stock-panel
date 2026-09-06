# ADR-22: Broker and QMT Boundary

## Status

Accepted, 2026-09-06.

## Decision

Phase 11 introduces a vendor-neutral Broker Protocol and a process-capable
QMT Agent Core. The application talks to normalized quote, order, fill,
account and reconciliation records. The default runtime is a deterministic
Mock Broker. An optional vendor-specific worker is available at
`backend/app/broker/qmt_vendor_agent.py`; it is launched only through the
explicit `QMT_AGENT_COMMAND` process boundary and is not imported by FastAPI.

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
- The Windows QMT worker implements the protocol without coupling the FastAPI
  application to vendor-specific objects.
- The worker keeps vendor order permission disabled unless
  `QMT_AGENT_ALLOW_ORDERS` is explicitly enabled. The application additionally
  requires `QMT_LIVE_ORDER_ENABLED`, a passing Small Live preflight and a
  one-time human activation. These controls do not replace account-owner
  approval or a supervised live acceptance run.
