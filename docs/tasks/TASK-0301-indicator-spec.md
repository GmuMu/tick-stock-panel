# TASK-0301 IndicatorSpec

## Task

- Branch: `feat/0301-indicator-spec`
- Scope: 将内置指标的名称、类别、输入列、依赖列、窗口、最小周期和版本固化为可验证规范。
- Boundary: `IndicatorSpec` 只描述元数据；指标计算表达式继续集中在 `backend/app/indicators/pipeline.py`，不复制第二套计算引擎。

## Implemented

- `backend/app/indicators/spec.py`
  - 新增不可变 `IndicatorSpec` 和 `INDICATOR_SPEC_VERSION = "1.0.0"`。
  - 注册全部公开指标及内部临时列。
  - 提供 `INDICATOR_SPECS`、`INDICATOR_DEPENDENCIES`、`INDICATOR_COLUMNS` 和 `ALL_INDICATOR_COLUMNS`。
  - 统一提供 `resolve_needed()` 依赖闭包、单项查询和稳定顺序枚举。
  - 启动时校验名称唯一、依赖存在、窗口有效和依赖无环。
- `backend/app/indicators/pipeline.py`
  - `compute_indicators()` 复用规范注册表解析 `needed` 和公开指标列集合。
  - 保留 `_INDICATOR_DEPS`、`_ALL_INDICATOR_COLS` 兼容旧调用方。
  - 计算表达式和输出行为保持在原 pipeline 中。
- `backend/tests/test_indicator_spec.py`
  - 覆盖版本与不可变性、名称唯一、公开列完整性、依赖闭包、无环、窗口/warmup 元数据和全量计算结果一致性。

## Acceptance

- [x] 所有公开指标均有唯一的 `IndicatorSpec`。
- [x] 内部临时列和跨指标依赖可被统一解析。
- [x] 依赖图启动时校验无环，`needed=None` 与历史全量列集合一致。
- [x] 计算逻辑未从 pipeline 复制或分叉。
- [x] 指标规范和相关回归测试通过。

## Verification

- `backend/.venv/Scripts/python.exe -m pytest tests/test_indicator_spec.py tests/test_indicator_needed.py tests/test_baseline_harness.py tests/backtest/test_matrix_strategy.py tests/test_enriched_full_rebuild.py tests/test_realtime_enriched_resume.py tests/test_live_enriched_metadata.py -q`：`52 passed`
- `backend/.venv/Scripts/ruff.exe check app/indicators/spec.py tests/test_indicator_spec.py --output-format concise`：通过
- `git diff --check`：通过

## Next Task

`TASK-0302 Indicator Golden Tests`：固化指标数值、列集合和边界输入的 golden 测试。
