# TASK-0502 CN Market Rules

状态：DONE（2026-09-05）

## 实现

- `backend/app/price_limits.py` 提供版本化 `MARKET_RULES_VERSION` 和 `market_rules_contract()`。
- 固化主板、创业板、科创板、北交所涨跌幅，以及主板 ST 在 2026-07-06 前后的规则切换。
- 结果 provenance 和 stats 均记录市场规则版本/快照。
- 保持既有 T+1、涨停不可买、跌停不可卖、印花税卖出侧和 ETF 边界语义不变。

## 验收

- `backend/tests/test_price_limits.py`
- `backend/tests/backtest/test_cost_model.py`
- `backend/tests/backtest/test_engine_portfolio.py`
- `backend/tests/backtest/test_phase5_contracts.py`
