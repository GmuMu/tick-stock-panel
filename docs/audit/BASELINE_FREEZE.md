# Baseline Freeze

Status: `READY_FOR_TASK-0002`

Date: 2026-09-04

## Repository

- Repository: `shy3130/tick-stock-panel`
- Remote: `https://github.com/shy3130/tick-stock-panel.git`
- Branch at inspection: `main`
- Commit SHA: `bab609b2d42c4722d51260a6c2192bbf16ab9139`
- Commit: `fix(ai): DeepSeek thinking 禁用参数被 400 拒绝时去参重试 (#240 跟进)`
- Worktree status before this document: clean
- Baseline tag: `baseline-tsp-20260904-bab609b`

## Repository Layout

- Backend: `backend/`
- Frontend: `frontend/`
- Runtime data directory: `data/` (not present in the clean clone)
- Backend dependency lock: `backend/uv.lock`
- Frontend dependency lock: `frontend/pnpm-lock.yaml`
- Windows launcher: `dev.ps1`

## Declared Runtime

- Python: `>=3.11`
- Node.js: `>=20`
- uv: required by `dev.ps1` and backend workflow
- pnpm: `9.10.0` declared in `frontend/package.json`
- Backend default port: `3018`
- Frontend default port: `3011`
- Data directory default: `./data`

## Runtime Observed

- Git: `2.30.2.windows.1`
- System PATH Node.js: `v12.13.1`
- System PATH pnpm command: `11.19.0`
- Effective backend Python: `3.12.14` from the Codex workspace runtime
- Effective uv: `0.12.9` installed at `C:\Users\admin\AppData\Roaming\Python\Python312\Scripts\uv.exe`
- Effective frontend Node.js: `v24.19.0` from the Codex workspace runtime
- Effective frontend pnpm: `11.19.0`
- `backend/.venv`: created by `uv sync --frozen`
- `frontend/node_modules`: installed with `pnpm install --frozen-lockfile`
- Repository `data/`: not present
- Temporary startup data: `%TEMP%\tsp-baseline-data-20260904`

The system PATH contains unsupported legacy Node.js, so frontend and Node-backed
tests must use the effective Node 24 runtime explicitly. The repository's declared
pnpm version is 9.10.0; pnpm 11 was used because it is the available compatible
tool and the lockfile passed its supply-chain and resolution checks.

## Startup and Verification

Completed:

- Backend install: `uv sync --frozen` passed with Python 3.12.14.
- Frontend install: `pnpm install --frozen-lockfile` completed after approving the
  locked `esbuild` postinstall script.
- Frontend build: `pnpm build` passed (`tsc -b && vite build`).
- Backend startup: passed with `uvicorn app.main:app --host 127.0.0.1 --port 3018`.
- `GET /health`: `200`, body `{"status":"ok","version":"0.2.2","mode":"none"}`.
- `GET /openapi.json`: `200`.
- `GET /api/settings/capability-matrix`: `200`.
- Frontend Vite startup: passed at `http://127.0.0.1:3011/`.
- Backend full pytest before the event fix: `1509 passed, 3 failed, 106 warnings`.
- Mining event fix targeted pytest: `11 passed`.
- Backend full pytest after the event fix, with Node 24 on PATH:
  `1512 passed, 106 warnings`.
- Backend Ruff scan: failed with `1523` existing findings under the current Ruff
  version; no bulk cleanup was attempted during baseline capture.
- `git diff --check`: passed for the audit changes.

The three original Mining Manager failures were fixed by making terminal state
transitions and their corresponding events persist under one store lock:

- `tests/test_mining_manager.py::test_cancel_while_waiting_for_capacity_never_calls_runner`
- `tests/test_mining_manager.py::test_runner_exception_marks_failed_and_appends_error_event`
- `tests/test_mining_manager.py::test_budget_exhausted_result_uses_distinct_success_status`

The original stock-sdk bridge failure was an environment issue: the test used the
unsupported system PATH Node runtime. It passes with the effective Node 24 runtime.

## Data Snapshot

No user data was found in the clean clone. No data backup or copy was created. The
runtime data location to snapshot after initialization is:

```text
E:\AAAA\0code\TSP\tick-stock-panel\data\
```

The repository `.gitignore` excludes runtime data. Credentials, databases, Parquet
files, logs, and user strategies must remain outside Git.

## Next Action

`TASK-0001` is ready for acceptance. `TASK-0002` can begin on the audit branch.
The repository is still not ready for business feature implementation until
`TASK-0002` through `TASK-0004` complete.
