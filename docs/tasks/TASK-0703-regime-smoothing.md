# TASK-0703 Regime Smoothing

状态：DONE（2026-09-05）

## 实现

- `PhaseSmoothingState` 固化 EMA、5 日回看、两日确认和当前/待确认阶段。
- `classify_phase_series_with_state()` 支持把阶段序列拆成多批处理，并从上一批状态继续计算。
- `regime_history/phase_state.json` 保存最终状态；写入采用临时文件替换，避免中断留下半份状态。
- 版本不匹配或损坏的 sidecar 会被拒绝并回退到全量重算。

## 验收

- `backend/tests/test_market_phase.py::TestClassifyPhaseSeries::test_stateful_chunks_match_single_pass`
- `backend/tests/test_market_phase.py::TestRefreshPhaseLabels::test_roundtrip_writes_phase_keeps_state`
- 38 个市场环境定向回归通过
