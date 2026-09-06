# TASK-1101 Broker Protocol

Status: DONE (2026-09-06, mock-safe boundary)

`backend/app/broker/protocol.py` defines the minimal adapter contract for
connection status, quote snapshots, order requests, orders, fills, account
snapshots and execution modes. All records expose normalized status and
provenance fields. The protocol has no vendor SDK dependency.

`backend/app/broker/mock.py` implements the deterministic no-network adapter
used by tests and local development. A real broker adapter must implement this
contract behind the Agent boundary and must not leak vendor types into the
application.
