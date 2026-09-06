# TASK-1003 OMS State

Status: DONE (2026-09-06)

`paper_orders` implements the local OMS states `new`, `accepted`,
`partially_filled`, `filled`, `cancelled` and `rejected`. The current public
paper path creates an accepted order only after Risk passes; fills enforce
remaining quantity and terminal-state boundaries. Order revisions and audit
events make transitions inspectable.
