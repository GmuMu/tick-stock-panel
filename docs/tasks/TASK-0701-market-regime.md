# TASK-0701 Market Regime

状态：DONE（2026-09-05）

## 实现

- `backend/app/services/regime_builder.py` 统一以 `kline_daily_enriched` 作为市场环境输入，并保留日级状态、评分、阶段和质量字段。
- `get_regime_coverage()` 对比 enriched 日期与 regime 历史，返回 source coverage、缺失日期、stale 日期及 `DataQuality`。
- `/api/regime/coverage`、`/history`、`/latest`、`/states` 统一返回质量信息，异常时 fail-closed，不把缺口伪装成完整数据。
- `quality_status` 支持 `FRESH`、`PARTIAL`、`STALE`、`MISSING`、`INVALID`。

## 验收

- `backend/tests/test_regime_builder.py`
- `backend/tests/test_market_phase.py`
- 定向回归：38 passed
- Python compileall 与 `git diff --check` 通过
