# ADR-24: Phase 13 Operations Boundary

Date: 2026-09-06

## Decision

Phase 13 provides local, explicit operational tooling without changing the
paper/mock trading safety boundary:

1. Runtime data is backed up as a manifest/checksum ZIP and is never committed
   to Git.
2. Backup validation is safe by default; full restore requires an explicit
   local confirmation and leaves a rollback directory.
3. HTTP observability uses a bounded in-memory metric snapshot and a
   correlation ID. Logs are filtered for common credential patterns.
4. Secret rotation exposes metadata only.
5. An external broker Agent is read-only by default. Mutation capabilities are
   granted only by an internal caller that already owns the safety controller.

## Consequences

The system is easier to diagnose and recover while remaining suitable for a
self-hosted single process. Metrics are not durable across restarts, and
real QMT, live market data, and automatic trading remain disabled pending the
separate Phase 12 safety review.
