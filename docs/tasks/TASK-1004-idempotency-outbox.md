# TASK-1004 Idempotency / Outbox

Status: DONE (2026-09-06)

Paper order acceptance and fill confirmation write a unique Outbox event in
the same SQLite transaction as the domain state. Retry keys replay the stored
response; `client_order_id` is unique; Outbox records expose pending/sent/
failed state, attempts and the last error. The implementation deliberately
does not call an external delivery endpoint.
