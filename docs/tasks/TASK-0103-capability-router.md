# TASK-0103 Capability Router

## Task

- Branch: `feat/0101-canonical-contracts` (当前工作树继续开发，未自动提交)
- Scope: 按数据能力选择请求源，统一 TickFlow fallback 和可序列化 provenance。
- Rule: Strategy/Backtest 不直接依赖供应商 SDK；自定义源返回空数据时不擅自切换数据源。

## 实现

- `backend/app/data_providers/base.py`
  - 新增不可变 `ProviderRoute`，统一保存 `requested_provider`、`effective_provider`、`fallback` 和 `fallback_reason`。
  - `provenance()` 只输出稳定、可序列化的路由证据，不暴露 provider 对象或 API Key。
- `backend/app/data_providers/custom/loader.py`
  - 新增 `resolve_route()`，统一处理 TickFlow、数据集未声明和 Provider 解析异常。
  - 固定路由原因：`dataset_unavailable`、`provider_resolution_failed`、`provider_call_failed`、`provider_contract_failed`。
- `backend/app/services/kline_sync.py`
  - daily、adj_factor、minute、full_minute 统一经路由边界。
  - 自定义源调用异常或分钟时间契约异常时立即回退 TickFlow，并保留 provenance。
  - 保留 `_resolve_minute_provider()` 和 `_resolve_full_minute_provider()` 的旧 tuple 兼容行为。
- `backend/app/services/quote_service.py`
  - realtime 行情统一经路由边界，状态接口增加 `realtime_route`。
  - 自定义实时源失败时回退 TickFlow，不让供应商异常中断全市场行情流程。
- `backend/app/services/minute_refresh.py`
  - `full_minute` 状态增加 `route_provenance`。
  - 自定义全量/增量端点调用失败时立即使用 TickFlow；状态查询不会覆盖最近一次失败证据。
- `backend/tests/test_capability_router.py`、相关数据源测试
  - 覆盖正常路由、数据集缺失、解析失败、调用失败和契约失败。
  - 覆盖 daily、adj_factor、minute、full_minute、realtime 的降级证据。

## 验收

- AC result: `PASS`
- capability 路由统一使用 `ProviderRoute`：`YES`
- TickFlow 是明确的安全 fallback：`YES`
- fallback 原因可序列化且不泄漏 Provider/API Key：`YES`
- 自定义源空数据不被误判为失败：`YES`
- Strategy/Backtest 未新增供应商 SDK 直连：`YES`

## 验证

- `backend/.venv/Scripts/python.exe -m pytest ...`：`237 passed`
- `backend/.venv/Scripts/python.exe -m ruff check --select F ...`：通过
- `git diff --check`：通过
- 前端 `pnpm build`：未完成；当前 `node_modules` 被无 TTY 的 pnpm 依赖重建过程占用/移出，报 `EPERM`，属于本地环境问题，未判定为代码通过。

## 下一任务

`TASK-0104 DataQuality 与 MarketSession`：为数据质量、覆盖范围、交易时段和 stale 状态建立统一结果对象，并在缺失数据时 fail-closed。
