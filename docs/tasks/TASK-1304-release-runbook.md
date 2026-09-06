# TASK-1304 Release Runbook

Status: DONE (2026-09-06)

## Scope

Turn deployment, upgrade, migration, recovery, and rollback into a repeatable
checklist.

## Evidence

- `docs/deployment.md`
- `backend/scripts/backup_restore.py`
- `backend/app/services/backup.py`
- `docker-compose.yml`
- `dev.ps1`

The runbook now requires a clean working tree, dependency/build checks,
runtime-data backup, smoke checks, and a post-upgrade verification. Recovery
uses checksum validation and an explicit restore confirmation. Rollback keeps
the pre-restore tree and requires the service to be stopped before replacing
the active data directory.
