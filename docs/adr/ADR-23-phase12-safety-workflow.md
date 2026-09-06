# ADR-23: Phase 12 Safety Workflow

## Status

Accepted, 2026-09-06.

## Decision

Before any future live-account evaluation, the system must provide persisted
account reconciliation, auditable human confirmation and a passing
LIVE_SHADOW loop. These are implemented against the normalized Mock Broker
boundary only.

Human confirmation is bound to a normalized action/payload hash, expires, and
is consumed once. Reconciliation is read-only and retains history. The
LIVE_SHADOW result must prove that the quote, trade, fill and reconciliation
stages completed without network or real-order side effects.

`TASK-1204 Small Live` remains blocked. Passing local/mock safety tests does not
authorize a real account or automatic trading.
