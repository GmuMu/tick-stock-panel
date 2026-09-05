# TASK-0503 Validation Gate

状态：DONE（2026-09-05）

## 实现

- 统一拒绝码：`NO_DATA`、`NO_FORMAL_DATA`、`INSUFFICIENT_FORWARD_COVERAGE`、`MINUTE_COVERAGE_MISSING`、`DATA_GENERATION_CHANGED`、`NO_SIGNALS`、`CANCELLED`。
- 因子、策略和旧信号回测的失败结果均保留旧 `error` 字段，同时返回结构化 `validation`。
- HTTP 区间保护、分钟历史守卫和 SSE 错误事件均返回 `message` 加 `validation`。
- 批量因子结果支持 `PARTIAL_FAILURE`，不会把部分失败伪装为整体成功。

## 验收

- `backend/tests/backtest/test_phase5_contracts.py`
- `backend/tests/backtest/test_factor_batch.py`
- `backend/tests/backtest/test_factor_metrics.py`
- `backend/tests/backtest/test_minute_backtest.py`
