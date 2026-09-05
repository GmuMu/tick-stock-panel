# ADR-0001：Development Plan 与现有运行时边界

状态：Accepted
日期：2026-09-04
关联任务：`TASK-0004`

## 背景

当前仓库已经有一套可运行的选股、指标、回测、监控和数据源插件实现；Development Plan V1.0 还描述了 Canonical Contract、Provider Health、交易决策、OMS、QMT 等更严格的后续边界。两者存在同名概念，但并非同一套契约。

如果把已有相似功能直接标记为计划任务完成，后续会跳过数据质量、来源追踪、幂等、风险和安全门，造成“功能可见但验收不可证明”的隐性分叉。

## 决策

1. 计划任务只有在真实代码入口、调用链、测试和文档证据全部匹配时才标记 `DONE`。
2. 已有相似功能但缺少计划契约的任务标记 `PARTIAL`，优先扩展现有入口，不复制第二套引擎。
3. 找不到稳定入口的任务标记 `GAP`；依赖安全前置或外部环境的任务标记 `BLOCKED`。
4. `TASK-0101` 至 `TASK-0104` 是后续 Provider 和业务扩展的前置；先统一 symbol/date/unit、能力、质量和交易时段，再接新数据源。
5. 交易、OMS、QMT 相关功能默认 fail-closed；在 Risk、Idempotency、Audit、Reconcile 和 Kill Switch 完成前，不接真实交易，不启用 AUTO。
6. `TASK-0004` 只校准文档和边界，不修改业务源码，不改变现有运行时行为。

## 影响

- 后续实现优先使用 `backend/app/data_providers/*`、`backend/app/indicators/pipeline.py`、`backend/app/strategy/engine.py`、`backend/app/backtest/*` 和 `backend/app/strategy/monitor.py` 的现有边界。
- `backend/app/main.py`、`frontend/src/router.tsx`、`frontend/src/lib/api.ts` 等高冲突文件只有在现有扩展点无法表达需求时才修改。
- 数据目录、Key、日志、Parquet 和用户策略仍属于运行时数据，不进入 Git。

## 复核条件

当新增 Provider、交易状态或公共 API 时，必须重新检查本文 GAP Matrix、对应 ADR、契约测试和上游合并冲突点。
