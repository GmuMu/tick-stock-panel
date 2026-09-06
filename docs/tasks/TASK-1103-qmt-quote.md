# TASK-1103 QMT Quote

Status: DONE (2026-09-06, mock-safe quote adapter)

`backend/app/broker/adapters.py::QmtQuoteAdapter` and the broker runtime expose
normalized quote snapshots with `quality` and `provenance`. Fresh seeded mock
quotes are marked `FRESH`; missing quotes are `UNAVAILABLE` rather than being
silently treated as valid data.

The real QMT quote path remains blocked until a vendor adapter is deliberately
provided. No network request is made by this implementation.
