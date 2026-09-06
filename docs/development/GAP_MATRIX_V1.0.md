# Development Plan V1.0 GAP Matrix

校准日期：2026-09-06
仓库：`tick-stock-panel`
基线：`25e5680`
当前分支：`feat/0301-indicator-spec`

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
| TASK-0204 | DONE | `docs/data/DATA_GOLDEN_BASELINE.md` 与 `backend/tests/fixtures/provider_golden/market.json` 固化跨 Provider 日K、分钟、实时、除权和财务报告期口径；`tests/test_provider_golden.py` 及 132 个相关回归通过 | 进入 `TASK-0301`，抽出可版本化 IndicatorSpec |
| TASK-0205 | DONE | `backend/app/strategy/builtin/sequoia_*.py` 接入 Sequoia-X 的 6 个日线矩阵策略；`tests/test_sequoia_x_strategies.py` 覆盖注册、公式触发、历史不足和 RPS 横截面排名；普通矩阵策略由 25 个增至 31 个 | `PrivatePlacement` 依赖公司行为数据集，保留为数据缺口；随后回到 `TASK-0301` |

## Phase 3：指标规范与增量一致性

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0301 | DONE | `backend/app/indicators/spec.py` 提供版本化不可变 `IndicatorSpec`、完整指标/内部列注册表、依赖闭包和无环校验；`pipeline.py` 已复用规范；`tests/test_indicator_spec.py` 与 52 个相关回归通过 | 进入 `TASK-0302`，固化指标数值、列集合和边界输入 golden |
| TASK-0302 | DONE | `backend/tests/fixtures/indicator_golden/indicators.json` 固定 70 根离线日线输入、全部公开指标列和最新值；`tests/test_indicator_golden.py` 覆盖版本绑定、列集合、数值和边界；55 个相关回归通过 | 进入 `TASK-0303`，统一关键价位、复权价格和缺失质量状态 |
| TASK-0303 | DONE | `levels.py` 已明确 adjusted/canonical OHLC 口径并接入 `DataQuality`；`/api/stock-analysis/levels` 与 AI meta 暴露 `price_basis/data_quality`；`tests/test_price_levels_contract.py` 与 28 个相关回归通过 | 进入 `TASK-0304`，证明盘后 batch 与盘中 incremental 指标一致 |
| TASK-0304 | DONE | `compute_enriched_today` 与 live aggregation 已修正 EMA/RSI 状态窗口、样本方差和 close 极值口径；`tests/test_indicator_incremental_parity.py` 通过真实状态构建验证 batch/incremental 一致；31 个相关回归通过 | 进入 Phase 4 `TASK-0401`，补策略版本、生命周期和 provenance 合同 |

## Phase 4：策略合同与 EOD 执行

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0401 | DONE | `strategy/contract.py` 提供版本化 `StrategyContract`、生命周期、输入特征和执行 provenance；`StrategyEngine` 与策略 API 已统一接入；`tests/test_strategy_contract.py` 覆盖普通、矩阵、分钟、叠加和 reload 隔离 | 进入 `TASK-0402`，统一候选模型与来源字段 |
| TASK-0402 | DONE | `strategy/candidates.py` 提供稳定 `StrategyCandidate`/`StrategyCandidateBatch`、candidate/seed ID、评分、信号和 provenance；`StrategyEngine.run()` 与 screener API 已统一暴露；`tests/test_phase4_execution.py` 覆盖序列化与排序 | 进入 `TASK-0403`，固化每日 EOD seed |
| TASK-0403 | DONE | `services/eod_seeds.py` 提供原子 JSON 存储、同 seed 幂等和冲突保护；`GET /api/strategies/seeds` 提供策略/日期查询；候选批次携带版本、日期、来源和 `DataQuality` | 进入 `TASK-0404`，接入盘后编排 |
| TASK-0404 | DONE | `services/eod_runner.py` 复用 `ScreenerService`/`StrategyEngine`；`daily_pipeline.run_now` 在刷新视图后执行 `run_eod_seeds`，阶段失败进入 `stage_errors`；手动 EOD API 已接入 | 进入 `TASK-0405`，完成生命周期状态机 |
| TASK-0405 | DONE | `strategy/lifecycle.py` 提供持久化状态机、历史和源码 revision；策略 API 支持生命周期、复制、删除、revision 列表与回滚；非 active 策略 fail-closed；接口级回滚失败恢复测试已覆盖 | Phase 4 完成，进入 Phase 5 `TASK-0501` |

## Phase 5：回测与市场规则

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0501 | DONE | `backtest/contracts.py`、`backtest/engine.py`、`backtest/factor.py`、`backtest/strategy.py`、`services/backtest.py` 已统一窗口、warmup、forward tail、资产类型和 generation | 保持合同版本兼容，后续按新数据源补充 fixture |
| TASK-0502 | DONE | `price_limits.py` 提供版本化市场规则快照；策略、因子和旧信号结果均记录规则；既有撮合测试覆盖 T+1/涨跌停/成本/ETF 边界 | 后续仅在交易所规则变化时增版本 |
| TASK-0503 | DONE | 回测结果和 API/SSE 守卫统一返回 `validation`，覆盖范围、分钟能力、无信号、取消和 generation 变更拒绝码 | 新增入口必须复用 `BacktestValidation` |
| TASK-0504 | DONE | 策略、因子、旧信号、批量因子和 worker 均记录 `BacktestProvenance`；包含数据、指标、策略、参数、撮合、规则和 worker lineage | 后续扩展运行环境字段，不改变已有字段 |

## Phase 6：Watch、Alert 与 Delivery

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0601 | DONE | `strategy/watch_scope.py` 提供版本化 `WatchScope`；规则、引擎、API 和事件统一携带 scope snapshot；自选分组 revision 变化按标的精确失效，空/删除/读取失败均 fail-closed；33 个监控回归通过 | 进入 `TASK-0602`，补 rolling watch 独立状态契约 |
| TASK-0602 | DONE | `strategy/rolling_watch.py` 提供版本化状态合同；普通行情规则按标的维护 active/inactive 窗口、entered/continued/exited/expired 迁移和跨轮询去重；规则/API/前端支持 `rolling_window_seconds`；37 个监控回归通过 | 进入 `TASK-0603`，补 resonance 输入/输出与去重契约 |
| TASK-0603 | DONE | `strategy/resonance.py` 提供版本化共振状态合同；引擎按标的累计独立信号时间、窗口过期和 entered 去重；规则/API/前端/SSE 携带 resonance 快照；`tests/test_resonance.py` 与监控回归通过 | 进入 `TASK-0604` |
| TASK-0604 | DONE | `strategy/alert_rule.py` 提供统一 AlertRule 快照；旧规则 normalize 兼容、保存 revision 递增；规则列表/保存响应/普通与特殊告警事件均携带快照；继续复用单一 `MonitorRuleEngine` | 进入 `TASK-0605` |
| TASK-0605 | DONE | `services/alert_delivery.py` 提供 queued/sent/failed/skipped 状态、渠道独立 delivery ID、revision/错误/时间审计；SSE、系统通知、飞书、企微接入；企微网络/5xx 重试、4xx/业务错误不重试；128 个监控专项回归通过 | Phase 6 完成，进入 Phase 7 `TASK-0701` |

## Phase 7：Market Regime

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0701 | DONE | `services/regime_builder.py::get_regime_coverage`、`api/regime.py` 四个查询接口和 `DataQuality` 统一返回 source coverage、missing/stale 与 fail-closed 状态；`docs/tasks/TASK-0701-market-regime.md` | Phase 7 完成，进入 Phase 8 `TASK-0801` |
| TASK-0702 | DONE | `regime_builder._aggregate_daily` 统一 breadth、成交额加权 money effect 与质量组件；`market_mainline` 对 amount 缺失安全降级；`docs/tasks/TASK-0702-breadth-money-effect.md` | 进入 Phase 8 `TASK-0801` |
| TASK-0703 | DONE | `market_phase.PhaseSmoothingState`、stateful classifier、原子 sidecar `regime_history/phase_state.json` 与跨分片回归；`docs/tasks/TASK-0703-regime-smoothing.md` | 进入 Phase 8 `TASK-0801` |
| TASK-0704 | DONE | `frontend/src/pages/Regime.tsx` 展示质量、缺口、资金效应和资金评分曲线；`frontend/src/lib/api.ts` 完成类型契约；`docs/tasks/TASK-0704-regime-ui.md` | 进入 Phase 8 `TASK-0801` |

## Phase 8：Thesis、Trade Plan、Decision、Journal

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0801 | DONE | `services/transaction_store.py` 使用 `data/user_data/transactions.sqlite3`、WAL、事务、幂等键和不可变审计事件；`docs/adr/ADR-20-transaction-research-sqlite.md` | 进入 Phase 9 `TASK-0901`，后续备份任务纳入 SQLite WAL |
| TASK-0802 | DONE | `api/trading_research.py` 与 `frontend/src/pages/TradingResearch.tsx` 保存论点、证据、反证、状态、version/revision | 后续可接统一 Signal，不改变 Thesis 历史版本语义 |
| TASK-0803 | DONE | `trade_plans` 表和 `/api/trading-research/plans` 结构化标的、价位、仓位、有效期和 candidate provenance | 进入 Phase 9 Paper Loop，禁止绕过 Decision Gate 形成订单 |
| TASK-0804 | DONE | `decision_gates` 表和 transition API 支持 pending/approved/rejected/expired、理由、过期和审计 | 后续 Risk/OMS 只能消费已审计决定，不在本阶段下单 |
| TASK-0805 | DONE | `journal_entries` 与只读 `/api/trading-research/audit` 支持计划、决定、订单/成交预留字段和复盘日志 | 进入 Phase 9 `TASK-0901`，后续补 paper execution 回放 |

## Phase 9：Unified Signal、Paper Loop、Review

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-0901 | DONE | `strategy/unified_signal.py` 定义版本化 Signal、确定性 ID、策略/监控适配器；`paper-trading/signals` 持久化 | 保持适配层，不改写既有生产者语义 |
| TASK-0902 | DONE | `TransactionStore.submit_paper_order/simulate_fill` 串起 Decision Gate、Risk、Paper OMS、模拟成交、Outbox 和 Position Projection；`paper-trading` API/页面可操作 | 仅 paper/mock，Phase 11 前不连接 Broker/QMT |
| TASK-0903 | DONE | `daily_reviews` 保存按执行日的 Signal、Risk、订单、成交、持仓不可变快照；`paper-trading/reviews` 与页面可查看 | 后续可接入更丰富的 Review 分析，不改变快照语义 |

## Phase 10：Risk 与 OMS

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-1001 | DONE | `services/risk_engine.py` 提供版本化 `RiskDecision`、结构化拒绝码和 fail-closed 输入快照；`risk_checks` 表/API 审计 | 仅用于 paper loop，真实账户风险需后续对账后再扩展 |
| TASK-1002 | DONE | 默认规则覆盖 Gate、计划有效期、价位关系、仓位/暴露、最小单位、T+1、涨跌停、行情质量和连续竞价 | 规则版本随市场规则变化显式升级 |
| TASK-1003 | DONE | `paper_orders` 状态 `accepted/partially_filled/filled/cancelled/rejected`，剩余数量和成交边界受事务约束 | Broker 状态映射留给 Phase 11 |
| TASK-1004 | DONE | `idempotency_keys`、唯一 `client_order_id`、同事务 Outbox、pending/sent/failed/attempts/error 与恢复 API | 不向外部 Webhook 或券商投递 |
| TASK-1005 | DONE | `position_projection.py` 只消费 confirmed paper fill，独立 `positions` 表支持成本、可卖数量、实现盈亏和 T+1 settle | 后续对账必须以 projection 为消费边界 |

## Phase 11：Broker 与 QMT

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-1101 | DONE | `backend/app/broker/protocol.py` 定义 BrokerAdapter、Quote/Order/Fill/Account 合同；`broker/mock.py` 提供无网络 mock | 真实券商适配器必须实现同一协议，不得把 vendor 类型带入应用 |
| TASK-1102 | DONE | `broker/agent.py::QmtAgentCore`、`broker/agent_process.py` 提供隔离 JSONL Agent 边界；`vendor_sdk_loaded=false` | Windows QMT SDK 仍需作为独立 Agent 部署，当前不加载真实 SDK |
| TASK-1103 | DONE | `broker/adapters.py::QmtQuoteAdapter` 和 `/api/broker/quote` 返回 `quality/provenance`；未注入行情返回 `UNAVAILABLE` | 真实 QMT 行情接入留给后续显式 vendor adapter |
| TASK-1104 | DONE | `broker/adapters.py::QmtTradeAdapter`、`/api/broker/orders` 支持 HUMAN_CONFIRM/LIVE_SHADOW mock；AUTO 和未配置 QMT fail-closed | 不启用真实下单，后续接入仍需人工确认和对账前置 |
| TASK-1105 | DONE | `broker/reconcile.py`、`/api/broker/reconcile` 对账户/订单/成交/持仓做只读结构化对账并记录事件 | 真实账户快照由未来 QMT Agent 提供 |
| TASK-1106 | DONE | `broker/safety.py` 持久化 Kill Switch、模式和原因；`/api/broker/safety/*`；断连/无确认/AUTO 全部拒绝 | 默认 HUMAN_CONFIRM，真实订单永久关闭直到后续安全评审 |

## Phase 12：Reconcile、Human Confirm、Small Live

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-1201 | DONE | `services/account_reconcile.py`、`/api/broker/reconcile`、`/api/broker/reconciliations` 保存账户/订单/成交/持仓对账历史 | 当前为 normalized Mock Broker；真实账户快照仍需独立 QMT Agent |
| TASK-1202 | DONE | `services/human_confirm.py`、`/api/broker/confirmations/*` 实现申请、批准、过期、内容哈希和一次性消费 | HUMAN_CONFIRM 已接入 Broker UI；不等于授权真实账户 |
| TASK-1203 | DONE | `services/live_shadow.py`、`/api/broker/live-shadow/run`、`tests/test_phase12_safety_workflow.py` 验证 quote→trade→fill→reconcile | 仅 mock-only；结果明确 `real_order_submitted=false` |
| TASK-1204 | BLOCKED | 真实 QMT SDK、账户凭证、发布 runbook 和实盘审批尚未提供；AUTO 仍禁用 | 必须通过真实 Agent 安全评审后才能讨论小额实盘，当前禁止自动交易 |

## Phase 13：运维与发布

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-1301 | DONE | `services/backup.py`、`scripts/backup_restore.py`、`tests/test_phase13_operations.py` | 原子 ZIP manifest/SHA-256 校验；恢复需本地显式确认并保留回滚目录 |
| TASK-1302 | DONE | `observability.py`、HTTP middleware、`/api/ops/metrics`、`tests/test_phase13_operations.py` | 已统一 correlation id、有限路由 metrics、错误摘要和日志脱敏 |
| TASK-1303 | DONE | `secrets_store.py` rotation metadata、`/api/ops/security/secrets/*`、Agent permissions | 密钥轮换仅返回元数据；外部 Agent 默认只读；真实 QMT 仍关闭 |
| TASK-1304 | DONE | `docs/deployment.md`、`TASK-1304-release-runbook.md`、备份 CLI | 已补升级、迁移、恢复、回滚、构建和 smoke checklist |

## Phase 14：Research Adapter 与 ML

| Task | 状态 | 真实证据 / 入口 | 下一步 |
| --- | --- | --- | --- |
| TASK-1401 | DONE | `research/contract.py` 定义版本化 `ResearchArtifact` 与只读 `ResearchAdapter` | 外部研究结果必须携带 symbol/as-of/provenance/fingerprint |
| TASK-1402 | DONE | `research/quantmind.py`、`/api/research/quantmind` 提供本地 JSON handoff | 当前为无网络本地适配；真实 QuantMind 网络连接需另行安全评审 |
| TASK-1403 | DONE | `research/ml_signal.py`、`/api/research/ml/signals` 接入 `UnifiedSignal(source=ml)` | ML 只写 Signal，不创建订单、不绕过 Decision/Risk |
| TASK-1404 | DONE | `tests/test_phase14_research_ml.py` 验证 research/ML 与 OMS/Broker 隔离 | 研究文件独立存储并纳入运行数据备份 |

## 执行结论

1. `TASK-0101` 至 `TASK-0104`、`TASK-0201` 至 `TASK-0205`、`TASK-0301` 至 `TASK-0304`、`TASK-0401` 至 `TASK-0405`、Phase 5 `TASK-0501` 至 `TASK-0504`、Phase 9 `TASK-0901` 至 `TASK-0903`、Phase 10 `TASK-1001` 至 `TASK-1005`、Phase 11 `TASK-1101` 至 `TASK-1106`、Phase 12 `TASK-1201` 至 `TASK-1203`、Phase 13 `TASK-1301` 至 `TASK-1304` 和 Phase 14 `TASK-1401` 至 `TASK-1404` 已完成当前阶段的 mock-safe/operations/research 契约，当前分支为 `feat/0301-indicator-spec`；Sequoia-X 的 `PrivatePlacement` 因公司行为数据缺口暂不实现。
2. `full_minute` YAML 解析断点仍是已确认缺口，依赖它的自定义全量分钟任务不得宣称端到端完成。
3. Phase 9/10/11/12-1201/1202/1203、Phase 13 和 Phase 14 已完成当前的 paper/mock/isolated-agent/operations/research 契约，但真实 QMT SDK、网络行情、真实账户和实盘仍保持关闭；TASK-1204 继续阻塞，当前禁止自动交易。
4. 以后每个 Task 必须先补契约测试，再实现代码；完成后更新对应 `docs/tasks/TASK-xxxx-*.md`，不以“页面能打开”代替验收。
