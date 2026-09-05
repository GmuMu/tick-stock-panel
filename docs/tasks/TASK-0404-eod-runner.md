# TASK-0404 EOD Runner

## Task

- Branch: `feat/0301-indicator-spec`
- Scope: 在盘后数据管道完成后编排策略执行并生成 EOD seeds。
- Boundary: 只做编排；数据加载复用 `ScreenerService`，策略执行复用 `StrategyEngine`，不直接调用供应商 SDK。

## Implemented

- `backend/app/services/eod_runner.py`
  - 选择最新 enriched 日期或调用方指定日期。
  - 仅选择支持 `stock`/`1d` 且生命周期为 `active` 的策略。
  - 通过共享 `ScreenerService.build_strategy_context` 装配数据，再调用 `StrategyEngine.run_all`。
  - 将每个结果转换为 `StrategyCandidateBatch` 并写入 `EODSeedStore`。
  - 返回策略数、seed 数、候选数、耗时和数据质量。
- `backend/app/jobs/daily_pipeline.py`
  - 在 `refresh_views` 后增加 `run_eod_seeds` 阶段。
  - 阶段失败进入 `stage_errors`，使任务终态为 failed，而不是误报成功。
- `backend/app/api/strategy.py`
  - `POST /api/strategies/eod/run` 支持不重复同步数据的手动执行。

## Acceptance

- [x] 盘后 runner 不复制数据或策略执行逻辑。
- [x] disabled/research/不支持资产或周期的策略不会被执行。
- [x] 结果含日期、数据质量和候选 provenance。
- [x] EOD 阶段失败可观测并阻断“假成功”。

## Verification

- `backend/.venv/Scripts/python.exe -m pytest tests/test_phase4_execution.py tests/test_data_integrity.py tests/test_mining_schedule.py -q`: 通过。
- Phase 4 相关回归：`97 passed`。
- `git diff --check`: 通过。

## Next Task

按 GAP Matrix 进入 `TASK-0405 Strategy Lifecycle`。
