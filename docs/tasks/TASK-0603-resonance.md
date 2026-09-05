# TASK-0603 Resonance

状态：DONE（2026-09-05）

## 实现

- `backend/app/strategy/resonance.py` 定义版本化 `ResonanceState` 合同，明确 `inactive/pending/active` 状态和 `entered/continued/expired` 迁移。
- 每个信号保存独立时间戳，在 `resonance_window_seconds` 内累计不同信号；达到 `resonance_min_signals` 才进入共振。
- 共振状态与普通规则 rolling watch、cooldown 分离，同一标的持续满足不重复触发，窗口过期后可重新进入。
- `MonitorRuleEngine`、规则校验、API、前端编辑器和 SSE/告警记录均支持共振字段及状态快照。

## 验收

- `backend/tests/test_resonance.py`
- 共振 pending/entered/continued/expired、窗口重置、冷却抑制、非法条件和事件快照已覆盖。
- Phase 6 监控专项回归：`128 passed`。
