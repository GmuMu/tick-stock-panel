# TASK-0602 Rolling Watch

状态：DONE（2026-09-05）

## 实现

- `backend/app/strategy/rolling_watch.py` 定义版本化 `RollingWatchState` 合同，明确 active/inactive 状态、entered/continued/exited/expired 迁移和可序列化字段。
- `MonitorRuleEngine` 为普通 `signal`、`price`、`market` 规则维护独立的 `(rule_id, symbol, event_type)` 状态，不把状态去重混入 `_last_fire` cooldown。
- 同一条件跨轮询持续命中只在首次进入时触发；条件回落后重新命中可再次触发；标的暂时缺失超过 `rolling_window_seconds` 后重新命中视为新进入。
- 冷却期只抑制重新进入时的通知，不会让持续命中的条件在 cooldown 到期后重复刷屏。
- 规则、API 和前端编辑器支持 `rolling_watch_contract_version` 与 `rolling_window_seconds`；事件/SSE 携带 `rolling_watch` 状态快照。
- 规则修改、删除、作用域成员移除和策略状态失效都会清理对应 rolling 状态，避免旧状态污染新规则。

## 验收

- `backend/tests/test_rolling_watch.py`
- `backend/tests/test_watch_scope_contract.py`
- `backend/tests/test_monitor_group_scope.py`
- `backend/tests/test_strategy_monitor_events.py`
- `backend/tests/test_intraday_monitor_signals.py`
- 定向监控回归：`37 passed`
- `backend/app/strategy/rolling_watch.py` 与 `backend/tests/test_rolling_watch.py` Ruff 检查通过。
- Backend Python 编译检查通过。

## 环境说明

- 对历史监控文件执行全文件 Ruff 时仍会报告本任务之前已有的格式/规则问题；本次新增模块和新增测试已单独通过 Ruff。
- 前端构建仍受环境依赖下载阶段的 npm `EACCES`/网络问题影响，未将其标记为通过。
