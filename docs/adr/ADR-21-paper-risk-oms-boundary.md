# ADR-21: Paper Risk and OMS Boundary

## Status

Accepted, 2026-09-06.

## Decision

Phase 9 and Phase 10 use the existing SQLite transaction store as the single
durable boundary for unified signals, risk checks, paper orders, simulated
fills, Outbox events, positions and daily review snapshots.

The paper loop is intentionally not a broker abstraction. It has no network
side effect and cannot submit to QMT or a real account. A paper order must
reference a Trade Plan with an approved Decision Gate, pass the versioned
fail-closed risk contract, and then enter the local OMS state machine.

Confirmed paper fills are the only input to the position projection. A-share
T+1 settlement is explicit: a buy fill is unavailable for selling until the
next settlement step. Every state-changing operation records a revision and an
immutable audit event; retry keys replay the original response.

## Consequences

- Existing strategy, indicator and monitor producers keep their original
  semantics and are adapted into `UnifiedSignal` snapshots.
- Missing data quality, market-session, price, lot-size, exposure or position
  information rejects the paper action instead of silently degrading.
- Outbox events can be inspected and marked sent/failed locally, but external
  delivery and live trading remain future phases.
