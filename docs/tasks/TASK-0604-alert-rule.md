# TASK-0604 Alert Rule

状态：DONE（2026-09-05）

## 实现

- `backend/app/strategy/alert_rule.py` 定义版本化 `AlertRule` 快照合同。
- 统一记录规则 ID、类型、条件、逻辑、作用域、rolling/resonance 参数、cooldown、启用状态、创建/更新时间和 revision。
- 规则保存时自动兼容旧规则并生成单调递增 revision；列表、保存响应和每次告警事件都返回不可变规则快照。
- 复用既有 `MonitorRuleEngine`，没有新增第二套告警引擎。

## 验收

- 普通规则、策略规则、日期、板块、异动、封单和放量事件统一附带 `alert_rule`。
- 旧规则缺少版本字段时由 `normalize()` 补齐 `alert_rule_contract_version=1.0` 和 `revision=1`。
- 共振事件测试验证规则快照与触发事件同时存在。
