# Development Plan V1.0 GAP Matrix

校准日期：2026-09-04
仓库：`tick-stock-panel`
基线：`25e5680`
当前分支：`feat/0101-canonical-contracts`

## 判定规则

- `DONE`：已有实现、测试和任务证据与计划验收边界一致。
- `PARTIAL`：存在可复用实现，但计划要求的统一契约、数据源或验收证据尚未完整。
- `GAP`：未发现可直接复用的真实入口，需要新增模块或接口。
- `BLOCKED`：依赖前置任务或外部运行环境，当前不能安全实现。

同名模块不等于同一任务已完成。只有代码入口、调用链、测试和文档边界都能对上，才提升为 `DONE`。

## Phase 0：基线与校准

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0001 | DONE | `docs/audit/BASELINE_FREEZE.md`，baseline tag 与运行环境记录 | 保留基线，不回写运行数据 |
| TASK-0002 | DONE | `docs/audit/CURRENT_CODE_AUDIT_TSP.md`，完成启动、扩展、Provider、Store、策略、回测、监控链审计 | 按 action items 排序 |
| TASK-0003 | DONE | `backend/tests/test_baseline_harness.py`，离线 smoke 覆盖 Provider、指标、策略、回测、监控、API | 进入计划校准 |
| TASK-0004 | DONE | 本文、`docs/adr/ADR-0001-plan-runtime-boundary.md`、任务记录 | 开始 `TASK-0101` |

## Phase 1：Canonical Contract 与 Capability Router

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0101 | DONE | `schemas.py` 提供 `normalize_symbol/date/epoch_ms/price/ratio/volume/amount` 与不可变 `CanonicalQuoteMeta`；daily、adj_factor、instrument normalizer 已接入，契约测试覆盖 Provider 边界 | 进入 `TASK-0102`，补正式 capability health/priority/status 契约 |
| TASK-0102 | DONE | `capabilities.py` 提供 `DataCapability`/`CapabilityMatrix` 类型、provider/source/priority/health/status；`/api/settings/capability-matrix` 注入全部路由字段；矩阵、API 和前端状态消费测试/构建通过 | 进入 `TASK-0103`，统一 fallback provenance |
| TASK-0103 | DONE | `ProviderRoute`/`custom.loader.resolve_route` 统一 daily、adj_factor、minute、full_minute、realtime 路由；自定义源调用/契约失败立即回退 TickFlow，`kline_sync`、`minute_refresh`、`quote_service` 暴露可序列化 provenance；237 个受影响测试通过 | 进入 `TASK-0104`，建立 DataQuality 与 MarketSession fail-closed 边界 |
| TASK-0104 | DONE | `market_time.py::MarketSession/market_session` 统一北京时间阶段、交易日、轮询窗口和连续竞价；`data_quality.py::DataQuality` 统一 coverage/stale/missing/invalid 与 fail-closed；minute-refresh、quote status 已接入，101 个受影响测试通过 | 进入 `TASK-0201`，实现最小 free-stockdb Bridge |

## Phase 2：外部数据源与 Provider 治理

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0201 | DONE | `plugins/freestockdb/bridge.py` 提供可配置 HTTP Bridge；`FreeStockDBProvider` 接入 daily、minute、realtime(Tick)、adj_factor 和 instruments，并经 custom loader/能力矩阵注册；32 个定向回归通过 | 进入 `TASK-0202`，定义 financial canonical schema |
| TASK-0202 | DONE | `data_providers/financial.py` 定义五张财务表 canonical schema；扶摇、TickFlow 和自定义 HTTP 财务源在 `financial_sync` 统一归一化，保留公告日、source 和扩展字段；28 个财务回归通过 | 进入 `TASK-0203`，集中实现 Provider health/retry/fallback |
| TASK-0203 | DONE | `data_providers/health.py` 提供线程安全 ProviderHealthRegistry、RetryPolicy、指数退避、错误脱敏和 fallback 记录；kline、minute、financial、quote 服务统一接入；`/api/settings/provider-health` 暴露状态与 error rate；83 个定向回归通过 | 进入 `TASK-0204`，建立跨 Provider golden baseline |
| TASK-0204 | GAP | 已有 Provider 单元测试，但无跨 Provider golden baseline | 依赖 0201/0202，新增 `docs/data/DATA_GOLDEN_BASELINE.md` 与 fixture |

## Phase 3：指标规范与增量一致性

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0301 | PARTIAL | `backend/app/indicators/pipeline.py::compute_all` 已是统一计算入口 | 抽出可版本化 `IndicatorSpec`，不复制 pipeline |
| TASK-0302 | PARTIAL | `test_*indicator*`、`test_enriched_*` 已有局部指标回归 | 增加 golden 值和列级契约 |
| TASK-0303 | PARTIAL | `backend/app/indicators/levels.py` 与股票分析服务已有关键价位 | 对齐价格口径、复权口径和缺失质量状态 |
| TASK-0304 | PARTIAL | `compute_enriched_today`、实时 enriched 与多个增量测试已存在 | 用同一 IndicatorSpec 证明 batch/incremental parity |

## Phase 4：策略合同与 EOD 执行

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0401 | PARTIAL | `StrategyEngine`、`StrategyDef`、`StrategyDataContext` 已存在，支持普通、矩阵、分钟、叠加策略 | 补计划要求的版本/lifecycle/provenance，不破坏当前注册表 |
| TASK-0402 | PARTIAL | `StrategyResult`、`backtest.candidates`、研究候选 API 已存在 | 统一候选模型与来源字段 |
| TASK-0403 | PARTIAL | `strategy_cache`、策略结果和候选库已存在；缺少计划定义的 EOD seed 契约 | 明确 seed 输入、日期和数据质量 |
| TASK-0404 | PARTIAL | `jobs.daily_pipeline`、`pipeline` API、调度器已存在 | EOD runner 只编排标准服务，补任务状态与 provenance |
| TASK-0405 | PARTIAL | 策略加载、删除、AI/组合目录已有生命周期处理 | 补稳定 ID、发布/停用/回滚的正式状态机 |

## Phase 5：回测与市场规则

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0501 | PARTIAL | `backtest.engine`、`backtest.strategy`、`backtest.matrix` 已实现数据加载与撮合 | 统一 backtest data contract 和时间可得性证明 |
| TASK-0502 | PARTIAL | `price_limits.py`、`backtest.engine` 已处理 T+1、涨跌停、手续费、滑点 | 增加市场规则 golden fixtures，明确资产类型边界 |
| TASK-0503 | PARTIAL | 回测 API 有区间/分钟覆盖守卫和错误返回 | 将 validation gate 统一为可记录的拒绝原因 |
| TASK-0504 | PARTIAL | 回测交易记录、候选 provenance、数据 generation 已存在但未统一 | 增加完整 data/indicator/strategy provenance |

## Phase 6：Watch、Alert 与 Delivery

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0601 | PARTIAL | `MonitorRuleEngine` 已支持 symbols、all、watchlist_group 等 scope | 固化 Watch Scope 版本和失效语义 |
| TASK-0602 | PARTIAL | 监控引擎已有 cooldown、状态和持久化触发记录 | 对 rolling watch 做独立状态契约 |
| TASK-0603 | PARTIAL | `intraday_signals`、异动监控和监控规则已有信号路径 | 补 resonance 的输入/输出及去重测试 |
| TASK-0604 | PARTIAL | `monitor_rules` API、`MonitorRuleEngine`、SSE 与触发记录已存在 | 将计划 DSL 与现有规则兼容收敛，禁止第二套告警引擎 |
| TASK-0605 | PARTIAL | 飞书、企微/Webhook、系统通知和语音路径已有 | 统一 Delivery 状态、失败重试和审计记录 |

## Phase 7：Market Regime

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0701 | PARTIAL | `backend/app/services/market_phase.py`、`api/regime.py`、前端 Regime 页面已存在 | 对齐计划的 coverage/partial 与质量状态 |
| TASK-0702 | PARTIAL | breadth、money effect、mainline 服务与测试已存在 | 统一输入数据源和缺失处理 |
| TASK-0703 | PARTIAL | `test_market_phase.py`、`test_regime_builder.py` 已有平滑相关覆盖 | 补确定性 golden 与跨日状态 |
| TASK-0704 | PARTIAL | 前端已有 Regime 页面 | 若需新增 UI，优先使用 extension route/slot；不复制核心页面 |

## Phase 8：Thesis、Trade Plan、Decision、Journal

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0801 | GAP | 未发现计划所需 transaction DB、交易事件模型或独立仓储 | 先选存储边界并写 ADR，再实现 schema |
| TASK-0802 | GAP | 未发现正式 Thesis 模块；现有 AI reports/research 不是交易 thesis 契约 | 依赖 0801，Markdown/JSON 兼容需先定义 |
| TASK-0803 | GAP | 未发现 TradePlan 模型和 API | 依赖 0802 与策略候选 provenance |
| TASK-0804 | GAP | 未发现 DecisionGate 状态机 | 依赖 0803、风险状态和审计字段 |
| TASK-0805 | GAP | 未发现交易 Journal 领域模型；现有报告存储不能直接替代 | 依赖 0801/0804，先做只读审计闭环 |

## Phase 9：Unified Signal、Paper Loop、Review

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0901 | PARTIAL | 自定义信号、内置信号、策略信号和监控事件分散存在 | 新增统一 Signal 只做适配层，不能改写现有信号语义 |
| TASK-0902 | GAP | 未发现正式 paper execution loop 或 paper ledger | 依赖 0901、0804 与 OMS 前置约束 |
| TASK-0903 | PARTIAL | 市场复盘、AI reports、market recap 已存在 | 先定义 review 输入和不可变快照 |

## Phase 10：Risk 与 OMS

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-1001 | GAP | 未发现正式 risk contract 或 risk engine | 依赖 Decision/Plan，先只做 fail-closed 规则协议 |
| TASK-1002 | GAP | 未发现计划中的 risk rules registry | 依赖 1001 与市场规则 golden tests |
| TASK-1003 | GAP | 未发现 OMS 状态机 | 依赖 transaction DB、risk contract 和统一事件 |
| TASK-1004 | GAP | 未发现 idempotency/outbox 实现 | 依赖 1003，必须先定义唯一键和 crash recovery |
| TASK-1005 | GAP | 未发现持仓 projection | 依赖 1003/1004，禁止从订单日志临时推导 UI 状态 |

## Phase 11：Broker 与 QMT

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-1101 | GAP | 未发现 broker protocol | 依赖 OMS，先实现 mock protocol，不接真实交易 |
| TASK-1102 | GAP | 未发现 QMT agent core | 依赖 1101，Windows 集成必须隔离在 agent 进程 |
| TASK-1103 | GAP | 未发现 QMT quote adapter | 依赖 1101/0104，必须带 quote quality/provenance |
| TASK-1104 | GAP | 未发现 QMT trade adapter | 依赖 1102/1004，默认只能 HUMAN_CONFIRM/LIVE_SHADOW |
| TASK-1105 | GAP | 未发现 reconcile 服务 | 依赖成交回报、持仓 projection 和账户快照 |
| TASK-1106 | GAP | 未发现 QMT safety/kill switch | 依赖 1102-1105，AUTO 默认关闭 |

## Phase 12：Reconcile、Human Confirm、Small Live

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-1201 | GAP | 未发现 account reconcile 领域模块 | 依赖 QMT reconcile |
| TASK-1202 | GAP | 未发现 HUMAN_CONFIRM 审批模型 | 依赖 DecisionGate、OMS 和审计 |
| TASK-1203 | GAP | 未发现 LIVE_SHADOW 测试闭环 | 只能在 mock broker、reconcile、kill switch 完成后开始 |
| TASK-1204 | BLOCKED | 未发现小额实盘发布 runbook 或安全门 | 必须通过 1203 和 1106，当前禁止自动交易 |

## Phase 13：运维与发布

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-1301 | PARTIAL | `dev.ps1`、Docker、数据目录和认证配置已存在 | 补 backup/restore 演练，不把 data 纳入 Git |
| TASK-1302 | PARTIAL | 日志、任务记录、SSE 和数据状态 API 已存在 | 统一 metrics、事件 correlation id 和敏感信息过滤 |
| TASK-1303 | PARTIAL | 访问认证、Key 脱敏、插件失败隔离已存在 | 补 secret rotation、最小权限和外部 Agent 边界 |
| TASK-1304 | PARTIAL | `docs/deployment.md` 与启动脚本已存在 | 补回滚、数据恢复、迁移和发布检查清单 |

## Phase 14：Research Adapter 与 ML

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-1401 | GAP | 未发现独立 research adapter contract | 依赖 Unified Signal，先定义只读 research boundary |
| TASK-1402 | GAP | 未发现 QuantMind adapter | 依赖 1401，禁止影响 OMS/QMT 路径 |
| TASK-1403 | GAP | 未发现 ML signal lifecycle | 依赖 1402，必须走统一 Signal/Decision/Risk 生命周期 |
| TASK-1404 | GAP | 未发现 research isolation 测试 | 依赖 1403，验证研究代码不能改变交易状态 |

## 执行结论

1. `TASK-0101` 至 `TASK-0104`、`TASK-0201` 至 `TASK-0203` 已完成，当前分支为 `feat/0101-canonical-contracts`；下一步进入 `TASK-0204`，现有工作树改动仍由维护者决定提交或携带。
2. `full_minute` YAML 解析断点仍是已确认缺口，依赖它的自定义全量分钟任务不得宣称端到端完成。
3. 交易、OMS、QMT 和实盘相关任务全部保持 `GAP/BLOCKED`，在没有风险、幂等、审计和 Kill Switch 之前不接真实交易。
4. 以后每个 Task 必须先补契约测试，再实现代码；完成后更新对应 `docs/tasks/TASK-xxxx-*.md`，不以“页面能打开”代替验收。
