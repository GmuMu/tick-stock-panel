# 当前代码可达性与扩展审计

审计任务：`TASK-0002`

审计日期：2026-09-04

审计分支：`audit/0002-reachability`

审计基线：`25e5680 fix(mining): persist terminal events with state`

基线参考：[BASELINE_FREEZE.md](./BASELINE_FREEZE.md)

## 1. 审计结论

当前仓库已经具备继续进行二次开发的真实入口，核心数据流和扩展注册链是可追踪的；但在修复一个已确认的自定义 `full_minute` 配置解析断点前，不建议把“多源全量分钟接入”作为已完成能力对外承诺。

结论分级：

| 项目 | 结论 | 说明 |
| --- | --- | --- |
| 核心应用启动 | 可达 | `FastAPI` 生命周期创建存储、行情、调度、策略和监控服务，空数据目录可以降级启动 |
| 后端源码扩展 | 可达 | `backend/app/custom/*.py` 扫描、路由注册、启动钩子和通知格式化器均有真实实现 |
| 前端源码扩展 | 可达 | `frontend/src/custom/*/extension.tsx` 扫描，支持静态路由、导航和三个已使用插槽 |
| Provider 插件 | 可达 | `plugin.yaml` 驱动发现，依赖/Key 失败隔离；已存在扶摇和 stock-sdk 插件 |
| YAML 自定义源常规数据集 | 可达 | `daily`、`adj_factor`、`realtime`、`minute`、`financial` 已接入统一路由 |
| YAML 自定义源 `full_minute` | **不可达** | 配置解析器过滤掉该数据集，导致声明无法进入 Provider 注册表 |
| 策略、指标、回测、监控主链 | 可达 | 均通过 `KlineRepository`、`ScreenerService` 和 `StrategyEngine` 共享数据/策略契约 |
| 进入下一项业务开发 | 有条件可开始 | 可开始不依赖 `full_minute` 的任务；先修复该断点再开发依赖它的任务 |

## 2. 真实启动与注册链

### 2.1 FastAPI 入口

- 应用创建于 `backend/app/main.py:387-392`，生命周期由 `lifespan()` 包裹。
- `_application_lifespan()` 在 `backend/app/main.py:102-131` 创建 `DataStore`、`KlineRepository`，恢复中断的 Mining 任务，并启动后台缓存预热。
- 能力探测写入 `app.state.capabilities`，位置为 `backend/app/main.py:128-131`。
- 自定义数据源在 `backend/app/main.py:133-139` 加载；加载失败只记录警告，不阻断 TickFlow 基准路径。
- 行情服务和监控服务在 `backend/app/main.py:141-159` 创建并注入状态。
- 调度器在 `backend/app/main.py:161-168` 启动；分钟刷新、盘口服务、数据完整性检查、扩展数据拉取和财务调度器随后按可选能力启动。
- 策略目录在 `backend/app/main.py:239-248` 固定为内置、用户自定义、AI、组合四个目录。
- `StrategyEngine` 载入结果写入 `app.state.strategy_engine`，位置为 `backend/app/main.py:245-250`。
- `MonitorRuleEngine` 在 `backend/app/main.py:301-335` 完成策略引擎、数据目录、行业服务和历史加载器注入，并从磁盘加载规则。

核心路由由 `backend/app/main.py:451-477` 统一 `include_router` 注册。源码扩展路由在核心路由之后处理，入口位于 `backend/app/main.py:479-482`。

### 2.2 后端源码扩展

真实扫描入口是 `backend/app/extensions/loader.py:24-33`：只扫描 `app.custom` 下不以下划线开头的 Python 模块。每个模块必须提供：

- `EXTENSION_ID`；
- `EXTENSION_API_VERSION`；
- `setup(registrar)`。

配置阶段位于 `backend/app/extensions/loader.py:36-64`，失败扩展不会留下半注册状态。路由冲突检查位于 `backend/app/extensions/loader.py:67-86`，仅按 HTTP 方法和路径检查。

当前真实可注册的后端能力来自 `backend/app/extensions/registry.py:28-50`：

- `APIRouter`；
- `NotificationFormatter`。

注册表会在 `backend/app/extensions/registry.py:108-125` 按顺序冻结；没有自定义格式化器时使用默认通知格式化器。扩展启动钩子在核心数据层准备好之后调用，位置为 `backend/app/extensions/loader.py:89-111` 和 `backend/app/main.py:337-342`。

对扩展暴露的上下文是只读协议：`backend/app/extensions/contracts.py:12-23` 只提供 `get_name_map()` 以及 `data_dir`，不是整个 `app.state`。当前仓库的 `backend/app/custom/` 只有模板和 README，没有实际启用的业务扩展。

### 2.3 前端源码扩展

初始化顺序为：

1. `frontend/src/main.tsx:45-54` 先初始化前端扩展，再动态导入路由。
2. `frontend/src/extensions/bootstrap.ts:4-9` 用 `import.meta.glob('../custom/*/extension.tsx')` 扫描扩展。
3. `frontend/src/extensions/registry.ts:91-108` 按源码路径排序加载，单个模块失败只写入加载错误。
4. `frontend/src/router.tsx:40-75` 校验核心路径冲突并冻结注册表。

真实类型契约在 `frontend/src/extensions/types.ts:6-25`、`frontend/src/extensions/types.ts:37-58`：

- 静态绝对路径路由；
- 导航项必须引用同一扩展内已注册的路由；
- `layout.navigation.extra`；
- `stock-preview.footer`；
- `watchlist.toolbar`。

插槽真实使用位置为：

- `frontend/src/components/Layout.tsx:865-869`；
- `frontend/src/components/StockPreviewDialog.tsx:642-645`；
- `frontend/src/pages/Watchlist.tsx:1490-1494`。

每个插槽实例由 `frontend/src/extensions/ExtensionSlot.tsx:11-25` 包裹，渲染异常由 `frontend/src/extensions/ExtensionBoundary.tsx:13-31` 隔离，不会直接击穿宿主页面。

## 3. 数据到业务的调用链

### 3.1 Provider 与路由

基础 Provider 协议位于 `backend/app/data_providers/base.py:19-75`，标准接口覆盖标的、日 K、复权因子、分钟 K 和实时行情。内置基础注册表 `backend/app/data_providers/registry.py:6-14` 只有 TickFlow；可选插件由自定义 loader 动态增补。

能力注册表位于 `backend/app/data_providers/capabilities.py:28-90`，当前能力包括：`daily`、`adj_factor`、`realtime`、`minute`、`depth5`、`financial`、`full_minute`。能力矩阵在 `backend/app/data_providers/capabilities.py:147-200` 合并 TickFlow 档位、插件/自定义源声明和当前偏好，`usable` 以生效源是否真实出现在候选列表为准。

插件发现位于 `backend/app/data_providers/custom/loader.py:531-590`：

- 读取 `plugin.yaml`；
- 调用插件自己的 `check`；
- 不可用插件保留状态但不注册 Provider；
- 可用插件动态导入 entry 并写入 Provider 表。

当前内置插件清单：

- `backend/app/plugins/fuyao/plugin.yaml:1-13`：`realtime`、`daily`、`adj_factor`、`financial`；
- `backend/app/plugins/stocksdk/plugin.yaml:1-13`：`daily`、`adj_factor`、`minute`、`realtime`。

服务层路由证据：

- 日 K 自定义源优先、未声明时回退 TickFlow：`backend/app/services/kline_sync.py:172-228`；
- 分钟 K 自定义源解析、调用和时区守卫：`backend/app/services/kline_sync.py:692-750`；
- `full_minute` Provider 解析和失败降级：`backend/app/services/kline_sync.py:1067-1087`；
- 自定义 `full_minute` 批量/增量调用：`backend/app/services/kline_sync.py:1090-1158`；
- 实时行情及可选指数补拉：`backend/app/services/quote_service.py:611-650`。

### 3.2 存储与指标

`DataStore` 在 `backend/app/tickflow/repository.py:84-128` 创建数据目录、DuckDB 内存连接和 Parquet 视图。视图注册覆盖股票、指数、ETF 的日 K/enriched、分钟 K、复权因子、维表、财务和盘口数据，位置为 `backend/app/tickflow/repository.py:188-245`。

`KlineRepository` 是读写和缓存边界，创建于 `backend/app/tickflow/repository.py:332-388`：

- DuckDB 查询统一经过线程锁：`backend/app/tickflow/repository.py:390-406`；
- Parquet 读改写有独立写锁：`backend/app/tickflow/repository.py:335-341`；
- 最新 enriched、历史 enriched、维表、ETF 和指数均有进程内缓存；
- `get_enriched_latest()`、`get_enriched_history()` 和 `get_enriched_range()` 位于 `backend/app/tickflow/repository.py:1140-1225`；
- 股票、指数、ETF 日 K 和分钟 K 读取分别位于 `backend/app/tickflow/repository.py:1401-1602`。

指标流水线在 `backend/app/indicators/pipeline.py:1-15` 定义了窄表存储原则：Parquet 持久化基础行情列，指标和信号按需计算。盘后全量/增量入口是 `backend/app/indicators/pipeline.py:1392-1412`，按标的分批计算的内存保护逻辑位于 `backend/app/indicators/pipeline.py:1352-1389`。盘中只计算当日增量 enriched 的入口是 `backend/app/indicators/pipeline.py:1795-1818`。

因此当前真实主链是：

```text
Provider / TickFlow
  -> kline_sync / quote_service
  -> daily / minute Parquet
  -> KlineRepository / DuckDB / Polars cache
  -> indicators.pipeline
  -> enriched latest/history
  -> screener / strategy / backtest / monitor
  -> FastAPI / SSE
  -> frontend API / pages
```

### 3.3 选股与策略

`ScreenerService` 在 `backend/app/services/screener.py:36-103` 优先读取最新缓存或 Repository 历史缓存，未命中才扫描 Parquet 并计算指标；历史窗口加载器在 `backend/app/services/screener.py:204-285`。

`StrategyEngine` 的加载和隔离行为位于 `backend/app/strategy/engine.py:231-318`：

- 每个策略文件独立加载；
- 重复 ID 会让相关策略进入错误列表；
- 组合策略在第二阶段验证子策略引用；
- 单个错误不影响其他有效策略。

运行时统一参数入口为 `backend/app/strategy/engine.py:669-686`，上下文和资产/周期校验为 `backend/app/strategy/engine.py:654-667`。单策略执行在 `backend/app/strategy/engine.py:875-1010`，批量执行在 `backend/app/strategy/engine.py:1093-1150`。选股 API 通过 `ScreenerService.build_strategy_context()` 与 `StrategyEngine.run_all()` 接线，位置为 `backend/app/api/screener.py:500-575`。

当前内置目录包含 26 个 Python 文件，其中 1 个是 `research_only` 因子排名模板，因此普通策略清单为 25 个。运行时日志基线也确认加载 25 个策略。

### 3.4 回测

回测 API 的信号回测仍保留在 `backend/app/api/backtest.py:75-118`。策略回测入口在 `backend/app/api/backtest.py:376-385`，先执行区间、资产类型和分钟数据覆盖守卫。

策略回测不是直接在 API 线程中执行：

- API 组装 `StrategyBacktestConfig`，位置为 `backend/app/api/backtest.py:591-616`；
- 任务通过 `make_worker_task()` 序列化，位置为 `backend/app/backtest/worker.py:136-155`；
- Worker 使用 `spawn`，在 `backend/app/backtest/worker.py:169-225` 重新创建 `DataStore`、`KlineRepository`、`StrategyEngine` 和 `StrategyBacktestService`；
- 父进程通过队列接收进度和终态，位置为 `backend/app/backtest/worker.py:270-374`。

撮合与成本配置在 `backend/app/backtest/engine.py:47-94`，日线信号/成交时序和 T+1 相关状态机在 `backend/app/backtest/engine.py:648-767`。策略回测服务在 `backend/app/backtest/strategy.py:677-710` 和 `backend/app/backtest/strategy.py:1004-1095` 复用同一策略定义和依赖解析。

### 3.5 监控与通知

当前代码同时保留两套监控类：

- 旧的 `StrategyMonitorService` 定义于 `backend/app/strategy/monitor.py:99-229`；
- 当前主路径使用通用 `MonitorRuleEngine`，定义于 `backend/app/strategy/monitor.py:323-376`。

生命周期仍创建旧服务并写入 `app.state.strategy_monitor`，见 `backend/app/main.py:147-152`；但行情评估路径实际从 `app.state.monitor_engine` 取引擎，见 `backend/app/services/quote_service.py:1040-1064`。旧服务的兼容入口 `_get_strategy_monitor()` 已明确返回 `None`，见 `backend/app/services/quote_service.py:1547-1550`。这属于需要后续清理或迁移说明的结构性热点，不应在新功能中继续接入旧服务。

当前监控评估链：

1. `QuoteService._evaluate_monitors()` 只在连续竞价时段评估，位置为 `backend/app/services/quote_service.py:1040-1054`。
2. 股票、ETF、指数分别使用对应 enriched 快照，位置为 `backend/app/services/quote_service.py:1074-1139`。
3. `MonitorRuleEngine.evaluate()` 先准备矩阵策略快照，再按规则快照评估，位置为 `backend/app/strategy/monitor.py:587-708`。
4. 通用规则按 scope、类型和 cooldown 生成事件，位置为 `backend/app/strategy/monitor.py:1067-1143`。
5. 事件经过扩展通知格式化器后落盘、SSE、系统通知和 Webhook，位置为 `backend/app/services/quote_service.py:1140-1237`。

## 4. 已确认的可达性问题

### P1：YAML 自定义源的 `full_minute` 实际不可达

文档和服务层都声明该能力存在：

- 自定义源文档把 `full_minute` 列为支持数据集：`docs/custom-data-source.md:7-21`；
- 能力矩阵注册 `full_minute`：`backend/app/data_providers/capabilities.py:80-89`；
- loader 的配置清洗允许 `full_minute`：`backend/app/data_providers/custom/loader.py:424-433`；
- Provider 实现了 `get_intraday_batch()` 并调用 `full_minute`：`backend/app/data_providers/custom/provider.py:270-285`；
- 服务层通过 `provider_has_dataset(name, "full_minute")` 解析该能力：`backend/app/services/kline_sync.py:1067-1087`。

但真正把 YAML/字典转换为 `CustomSourceConfig` 的 `config_from_dict()` 仍只保留五类数据集：`backend/app/data_providers/custom/config.py:105-119`。同文件的 `DatasetName` 也未包含 `full_minute`：`backend/app/data_providers/custom/config.py:10`。

只读运行时探针结果：

```text
输入：仅包含 full_minute 的合法配置
输出：parsed_datasets=[]
输出：full_minute_present=False
```

因此 YAML 自定义源即使按 `docs/custom-data-source.md:15` 声明 `full_minute`，加载后也不会进入 `CustomSourceConfig.datasets`，`provider_has_dataset()` 最终返回 false，`_resolve_full_minute_provider()` 会降级而不是使用该源。该问题应在后续修复任务中补充配置类型、解析白名单、保存往返和真实 resolver 测试；在修复前不要把该能力视为端到端可用。

### P2：功能文档仍写 18 个内置策略

`docs/features.md:9-19` 写的是“18 个内置策略”，而：

- `docs/strategy.md:9-19` 写的是 25 个；
- `README.md:46` 写的是 25 个；
- `backend/app/strategy/builtin/` 当前有 26 个 Python 文件，扣除 `research_only` 模板后为 25 个普通策略。

这不会阻断运行，但会误导用户和开发验收，应在文档一致性任务中修正。

### P2：Provider 基础协议与 `full_minute` 运行契约分裂

`backend/app/data_providers/base.py:19-75` 的 `ProviderCapabilities` 没有 `full_minute` 字段，`MarketDataProvider` 也没有声明 `get_intraday_batch()` 或 `get_intraday_latest()`。实际实现依赖 `plugin.yaml` 的 datasets 声明和 `kline_sync.py` 的鸭子类型调用。

这不是当前普通 Provider 运行的阻塞点，因为能力矩阵和 loader 已承担了路由；但新插件开发者不能只实现 `MarketDataProvider` 就发现完整契约，必须同时阅读 `docs/plugin-development.md` 和 `kline_sync.py`。后续若修改 Provider 公共协议，应先明确是否把全量分钟扩展方法纳入正式 Protocol，避免出现第二套隐式接口。

### P2：旧策略监控服务仍被创建，但不再是主运行实现

如第 3.5 节所述，`StrategyMonitorService` 仍在生命周期创建，却不参与 `QuoteService` 的主监控评估。新代码如果误用 `app.state.strategy_monitor`，会接入已迁移前的旧路径。后续应选择“删除并清理兼容层”或“明确标记弃用并补迁移文档”，不建议继续扩展它。

## 5. 测试与验证覆盖

当前仓库统计到：

- 后端测试文件：164 个；
- 前端测试文件：0 个；
- 已有扩展测试：`backend/tests/test_extensions.py`；
- 已有能力矩阵测试：`backend/tests/test_capability_matrix.py`、`backend/tests/test_capability_augment.py`；
- 已有 Provider/自定义源测试：`backend/tests/test_fuyao_provider.py`、`backend/tests/test_stocksdk_provider.py`、`backend/tests/test_custom_minute_config.py`、`backend/tests/test_custom_pct_units.py`、`backend/tests/test_custom_batch_isolation.py`；
- 已有全量分钟路由和服务测试：`backend/tests/test_minute_refresh.py`、`backend/tests/test_minute_routing.py`、`backend/tests/test_full_minute_capability.py`；
- 已有策略、监控、回测和 Worker 测试矩阵，覆盖 `backend/tests/test_strategy_*.py`、`backend/tests/test_monitor_*.py` 及 `backend/tests/backtest/`。

覆盖缺口：

- 没有 YAML `full_minute` 从 `config_from_dict()` 到 `provider_has_dataset()` 的端到端契约测试；现有测试主要通过手工构造 Provider 或 monkeypatch 绕过了该解析断点。
- 没有前端扩展注册表的自动化测试；当前只能依赖 TypeScript 构建和人工检查。
- Provider 基础 Protocol 没有表达 `full_minute` 可选方法，类型检查不能发现插件遗漏该契约。

## 6. 高冲突热点与二开建议

高冲突文件来自当前真实调用链：

- `backend/app/main.py`：生命周期、路由注册、状态注入和调度器接线；
- `backend/app/strategy/engine.py`：策略加载、参数、实时矩阵和批量执行；
- `backend/app/backtest/engine.py`：撮合、成本、持仓状态机；
- `frontend/src/router.tsx`：核心路由和扩展路由冻结；
- `frontend/src/components/Layout.tsx`：全局布局、导航和导航插槽；
- `frontend/src/lib/api.ts`、`frontend/src/lib/queryKeys.ts`：前后端契约和缓存键。

二开优先级：

1. 不改变核心流程的页面局部内容，使用已存在的前端插槽。
2. 新页面使用前端扩展路由和导航注册。
3. 后端通知文案使用 `NotificationFormatter`，不要继承 `StrategyMonitorService` 或 `StrategyEngine`。
4. 新数据源优先实现 Provider/插件契约，不能从策略、监控或 API 直接调用供应商接口。
5. 只有现有扩展点无法表达真实业务行为时，才修改上述高冲突热点，并附带契约测试和上游升级复核记录。

## 7. TASK-0002 验收状态

状态：`AUDIT_COMPLETE_WITH_ACTION_ITEMS`

本任务已完成只读调用链审计，审计文档是本分支唯一新增文件。建议后续顺序：

1. 单独修复 `full_minute` 配置解析断点，并增加从配置解析到路由判断的回归测试。
2. 修正 `docs/features.md` 的策略数量。
3. 对旧 `StrategyMonitorService` 做弃用/删除决策，避免新代码继续接入旧路径。
4. 再进入依赖上述能力的业务功能开发或 `TASK-0003`。

在第 1 项未完成前，可以开始不依赖 YAML `full_minute` 的普通策略、页面、通知和分析功能开发；不应宣称“自定义源全量分钟端到端已支持”。
