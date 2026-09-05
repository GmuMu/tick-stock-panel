# TASK-0402 Candidate Model

## Task

- Branch: `feat/0301-indicator-spec`
- Scope: 为策略选股结果建立稳定、可序列化、可供后续回测引用的候选模型。
- Boundary: 复用现有 `StrategyResult` 和 `StrategyEngine`，不新增第二套策略执行引擎。

## Implemented

- `backend/app/strategy/candidates.py`
  - `StrategyCandidate` 固化 `candidate_id`、标的、日期、策略、排名、评分、原始行、命中信号和 provenance。
  - `StrategyCandidateBatch` 固化模型版本、策略、日期、候选列表、数据质量和 seed 引用。
  - `candidate_id` 与 `seed_id` 基于策略、日期、版本或标的确定性生成，支持幂等和后续复测关联。
  - `batch_from_result` 将普通、矩阵、分钟和叠加策略的既有结果统一转换。
- `backend/app/strategy/engine.py`
  - `StrategyEngine.run()` 在不改变既有结果字段的前提下附加候选模型和候选列表。
- `backend/app/api/screener.py`
  - 批量选股结果暴露 `candidate_model_version`、`candidates` 和 `provenance`。

## Acceptance

- [x] 候选具备稳定 ID、策略 ID、日期、排名和评分。
- [x] 候选保留命中信号、原始展示行和策略执行 provenance。
- [x] 结果可以安全 JSON 序列化，NaN/无穷值不会泄漏到 API。
- [x] 现有策略执行路径和旧 `StrategyResult` 调用方保持兼容。

## Verification

- `backend/.venv/Scripts/python.exe -m pytest tests/test_phase4_execution.py tests/test_strategy_contract.py tests/test_strategy_registry.py tests/test_screener_cache_api.py -q`: 通过。
- Phase 4 定向回归：`97 passed`。
- `git diff --check`: 通过。

## Next Task

按 GAP Matrix 进入 `TASK-0403 EOD Seeds`。
