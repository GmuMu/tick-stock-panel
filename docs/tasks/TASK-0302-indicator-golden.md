# TASK-0302 Indicator Golden Tests

## Task

- Branch: `feat/0301-indicator-spec`
- Scope: 用固定、离线、可重复的输入固化指标数值、列集合和边界输入。
- Rule: golden 测试不依赖真实 API Key、网络或运行中的数据服务。

## Implemented

- `backend/tests/fixtures/indicator_golden/indicators.json`
  - 固定 70 根日线 OHLCV 输入。
  - 绑定 `IndicatorSpec` 版本 `1.0.0`。
  - 固化全部公开指标列集合和最新一根的指标数值。
- `backend/tests/test_indicator_golden.py`
  - 验证 fixture 版本与指标规范一致。
  - 验证输出列集合没有缺列或多列。
  - 验证公开指标最新值，使用严格浮点容差。
  - 覆盖空 DataFrame、单根 K 线、零成交量等边界输入。

## Acceptance

- [x] 指标数值有固定 golden 基线。
- [x] 公开指标列集合有固定 golden 基线。
- [x] 指标规范版本变化会被测试发现。
- [x] 空输入、历史不足和零成交量边界有离线覆盖。
- [x] 测试不依赖网络或 Provider API Key。

## Verification

- `backend/.venv/Scripts/python.exe -m pytest tests/test_indicator_golden.py tests/test_indicator_spec.py tests/test_indicator_needed.py tests/test_baseline_harness.py tests/backtest/test_matrix_strategy.py tests/test_enriched_full_rebuild.py tests/test_realtime_enriched_resume.py tests/test_live_enriched_metadata.py -q`：`55 passed`
- `backend/.venv/Scripts/ruff.exe check tests/test_indicator_golden.py tests/test_indicator_spec.py app/indicators/spec.py`：通过
- `git diff --check`：通过

## Next Task

`TASK-0303 Price Level`：统一关键价位、复权价格和缺失质量状态。
