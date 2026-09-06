# ADR-20: Transaction Research SQLite Boundary

## Decision

Phase 8 uses one SQLite database at `data/user_data/transactions.sqlite3`.
The database contains thesis, trade plan, decision gate, journal and immutable
audit records. SQLite WAL and transactional writes are enabled; reads never
touch parquet or broker state.

## Scope

This boundary supports research and paper records only. It does not submit,
cancel or reconcile real orders, calculate positions, or connect to QMT/OMS.
Those responsibilities remain blocked until the later risk and execution
phases define their own contracts.

## Consistency

Every write has a generated or caller-supplied idempotency key and produces one
audit event. Updates use an expected revision and fail with a conflict when a
stale client writes. Runtime databases and user records are excluded from Git.

## Recovery

The schema is created idempotently on startup/request access. SQLite's WAL file
is part of the user data directory and must be included by the future backup /
restore task; it is never committed as a fixture.
