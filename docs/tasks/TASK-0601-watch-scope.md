# TASK-0601 Watch Scope

状态：DONE（2026-09-06）

## 实现

- `backend/app/strategy/watch_scope.py` 定义版本化 `WatchScope` 合同，统一 `all`、`symbols` 和 `watchlist_group` 的解析结果。
- 作用域快照记录 `contract_version`、`scope_version`、资产类型、规范化标的、来源 revision、状态和失效原因。
- 自选分组成员通过 `watchlist.revision()` 缓存失效；分组新增、移出、清空和删除会在下一轮评估生效。
- 空标的、空分组、分组不存在、分组读取失败和不支持的 scope 均 fail-closed，不会退化为全市场。
- 监控引擎对动态作用域只清理离开作用域标的的 cooldown、策略池、信号和异动状态；保留仍在组内标的状态。
- 监控事件、监控规则列表和保存响应均携带 `watch_scope` 快照；历史规则自动补齐 `scope_contract_version`。

## 验收

- `backend/tests/test_watch_scope_contract.py`
- `backend/tests/test_monitor_group_scope.py`
- `backend/tests/test_monitor_index.py`
- `backend/tests/test_strategy_monitor_events.py`
- 定向监控回归：`33 passed`
- 新增作用域模块和专项测试 Ruff 检查通过，Python 编译检查通过。
