# TASK-1301 Backup / Restore

Status: DONE (2026-09-06)

## Scope

Provide an explicit, auditable backup and restore path for the runtime
`data/` directory without adding user data to Git.

## Evidence

- `backend/app/services/backup.py`
- `backend/scripts/backup_restore.py`
- `backend/tests/test_phase13_operations.py`
- `docs/deployment.md`

Backups are atomic ZIP archives under `data/user_data/backups/`. Each archive
contains a schema-versioned manifest and SHA-256 checksum for every file.
Validation is read-only. Restore requires an explicit `--confirm`, stages the
archive first, and renames the previous data tree to a
`*.pre-restore-*` rollback directory.

## Operational boundary

The API exposes authenticated backup creation and listing. Restore remains a
local CLI action so a browser request cannot accidentally replace the complete
runtime data directory.
