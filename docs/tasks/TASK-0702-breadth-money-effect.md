# TASK-0702 Breadth / Money Effect

状态：DONE（2026-09-05）

## 实现

- breadth 统一由 enriched 的 `change_pct` 聚合涨跌家数、涨跌占比、均值、中位数和强弱分布。
- money effect 使用成交额加权涨跌幅 `sum(amount * change_pct) / sum(amount)`，无有效成交额时返回 null 并标记 `PARTIAL`。
- regime 与主线都从 `kline_daily_enriched` 读取；主线在 `amount` 缺失时安全降级为连板高度排序，核心列缺失则明确返回空结果。
- 综合评分增加资金效应权重，日级结果暴露 `money_effect_pct` 与 `money_effect_score`。

## 验收

- `backend/tests/test_regime_builder.py::test_aggregate_daily_money_effect_is_amount_weighted`
- `backend/tests/test_market_mainline.py`
- 定向回归：38 passed
