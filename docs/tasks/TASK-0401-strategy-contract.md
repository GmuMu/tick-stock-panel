# TASK-0401 Strategy Contract

## Task

- Branch: `feat/0301-indicator-spec`
- Scope: 在现有 `StrategyEngine` 上建立可验证的策略元数据、输入、生命周期、版本和执行来源合同。
- Boundary: 只规范化注册表和结果 provenance，不新增第二套策略执行引擎，不改变普通、矩阵、分钟和叠加策略的执行语义。

## Implementation

- `backend/app/strategy/contract.py`
  - 定义合同版本 `1.0`、策略版本默认值 `1.0.0`、生命周期枚举和执行后端枚举。
  - 校验稳定策略 ID、语义化版本、资产类型、时间周期和 required features。
  - 生成可序列化的 `StrategyContract` 及执行 provenance。
- `backend/app/strategy/engine.py`
  - 加载策略文件时统一补齐并校验 contract metadata。
  - 对矩阵策略纳入原始字段和静态 warmup；保留原有 `StrategyDef.required_features` 语义。
  - 通过 `StrategyEngine.run()` 为所有策略结果附加合同版本、策略版本、资产、周期、日期和输入特征。
  - 保持 reload 失败时上一版注册表不变。
- `backend/app/api/strategy.py`
  - 策略列表和详情暴露 `contract_version`、`lifecycle`、`required_features`、`warmup_bars` 和 `provenance`。

## Contract

策略合同至少包含：

- `contract_version`
- `strategy_id`
- `strategy_version`
- `source`
- `execution_backend`
- `lifecycle`
- `asset_types`
- `timeframes`
- `required_features`
- `entry_signals`
- `exit_signals`
- `lookback_days`
- `warmup_bars`
- `provenance`

默认生命周期为 `active`；`research_only` 策略默认生命周期为 `research`。当前生命周期字段只用于合同与展示，发布/停用/回滚状态机由 `TASK-0405` 处理。

## Acceptance

- [x] builtin、custom、AI、composite 和 minute 策略共享同一合同结构。
- [x] 缺省策略版本规范化为 `1.0.0`，缺省生命周期规范化为 `active`。
- [x] 非法策略 ID、版本和生命周期在加载期隔离，并记录 load error。
- [x] reload 失败时不污染上一版注册表。
- [x] `StrategyResult` provenance 可通过 API/dataclass 安全序列化。
- [x] 手工构造的旧 `StrategyDef` 仍可运行并获得兼容合同回退。
- [x] 不改变现有策略注册、矩阵、分钟、叠加、监控和回测调用路径。

## Verification

- `backend/.venv/Scripts/python.exe -m pytest tests/test_strategy_contract.py tests/test_strategy_registry.py tests/test_strategy_market_data.py tests/test_strategy_required_history.py tests/test_strategy_detail_signals.py tests/test_composite_strategy.py -q`: `52 passed`
- `backend/.venv/Scripts/python.exe -m compileall -q app/strategy/contract.py app/strategy/engine.py app/api/strategy.py tests/test_strategy_contract.py`: passed
- `git diff --check`: passed

## Next Task

按 GAP Matrix 进入 `TASK-0402 Candidate Model`。
