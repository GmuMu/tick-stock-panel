# TASK-0405 Strategy Lifecycle

## Task

- Branch: `feat/0301-indicator-spec`
- Scope: 为策略创建、发布、停用、复制、删除和源码回滚建立可持久化生命周期与审计证据。
- Boundary: 生命周期只控制既有 `StrategyEngine` 的注册和执行，不引入新的策略运行时。

## Implemented

- `backend/app/strategy/lifecycle.py`
  - 状态机支持 `draft`、`active`、`disabled`、`archived`、`research`。
  - 持久化状态、状态历史、迁移原因和源码 revision 元数据。
  - 源码快照保存到 `user_data/strategy_revisions/<strategy_id>/`。
  - 加载阶段只读生命周期，避免 reload 失败时污染生命周期文件。
- `backend/app/strategy/engine.py`
  - 统一应用持久化生命周期。
  - 非 `active` 策略 fail-closed，禁止通过引擎执行。
  - 提供生命周期查询、迁移和运行时注销。
- `backend/app/api/strategy.py`
  - `GET/POST /api/strategies/{id}/lifecycle`
  - `GET /api/strategies/{id}/revisions`
  - `POST /api/strategies/{id}/rollback`
  - `POST /api/strategies/copy`
  - 创建/更新/复制/删除均维护源码 revision 和生命周期；保存或回滚失败恢复原文件与注册表。

## Acceptance

- [x] 创建、更新、复制、删除和源码回滚具备稳定策略 ID 与来源校验。
- [x] 发布/停用状态迁移有合法边界、原因和历史记录。
- [x] 停用策略不会进入默认列表或被执行。
- [x] 回滚失败恢复原源码和运行时注册表。
- [x] 内置策略禁止删除、归档和源码回滚。

## Verification

- `backend/.venv/Scripts/python.exe -m pytest tests/test_phase4_execution.py tests/test_strategy_code_save.py tests/test_strategy_delete.py tests/test_composite_strategy_api.py tests/test_strategy_registry.py -q`: 通过。
- Phase 4 定向回归：`97 passed`。
- `git diff --check`: 通过。

## Next Task

Phase 4 完成，按 GAP Matrix 进入 Phase 5 `TASK-0501 Backtest Data`。
