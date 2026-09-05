# TASK-0504 Backtest Provenance

状态：DONE（2026-09-05）

## 实现

- 策略回测记录数据 generation、覆盖窗口、指标版本、策略 ID/版本/revision、参数、overrides、撮合配置和市场规则。
- 因子回测记录因子方法版本、数据覆盖、指标版本、成本/频率参数和市场规则。
- 旧信号回测补齐同一 provenance 合同，保持 vectorbt 入口不变。
- worker 的进程、RSS、序列化耗时和结果大小同时写入 `stats.worker` 与回测 `provenance.worker`。
- 矩阵回测保留真实源矩阵到结果装配阶段，避免 coverage 被释放后变成空值。

## 验收

- `backend/tests/backtest/test_phase5_contracts.py`
- `backend/tests/backtest/test_strategy_backtest_correctness.py`
- `backend/tests/backtest/test_composite_backtest_e2e.py`
- `backend/tests/backtest/test_worker_process.py`
