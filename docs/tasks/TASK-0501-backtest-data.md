# TASK-0501 Backtest Data

状态：DONE（2026-09-05）

## 实现

- `backend/app/backtest/contracts.py` 定义版本化 `BacktestDataCoverage`、`BacktestValidation` 和 `BacktestProvenance`。
- 策略、因子、旧信号三类回测均返回 `data_coverage`，覆盖 requested、load、warmup、simulation、forward tail、实际日期轴、标的数、行数和 generation。
- 因子回测加载正式区间后的实际交易日尾部；缺少五个前瞻交易日时 fail-closed。
- 回测在读取前后固定并校验 enriched generation。

## 验收

- `backend/tests/backtest/test_phase5_contracts.py`
- `backend/tests/test_backtest_warmup.py`
- 策略、因子、矩阵、分钟回测定向回归通过。
