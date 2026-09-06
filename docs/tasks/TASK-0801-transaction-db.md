# TASK-0801 Transaction DB

状态：DONE

`backend/app/services/transaction_store.py` establishes the SQLite boundary in
`data/user_data/transactions.sqlite3`. It initializes the schema idempotently,
uses WAL and `BEGIN IMMEDIATE`, closes Windows file handles, and stores
idempotency responses plus immutable audit events in the same transaction.

The database is deliberately separate from parquet, existing monitor files and
real trading. See `docs/adr/ADR-20-transaction-research-sqlite.md`.
