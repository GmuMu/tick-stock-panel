# TASK-0104 DataQuality 与 MarketSession

## Task

- Branch: `feat/0101-canonical-contracts` (当前工作树继续开发，未自动提交)
- Scope: 统一数据质量、覆盖/新鲜度和北京时间市场时段结果。
- Rule: 数据质量默认 fail-closed；未知交易日保留兼容的工作日近似，但确定休市必须停止轮询。

## 实现

- `backend/app/market_time.py`
  - 新增不可变 `MarketSession` 和 `market_session()`。
  - 统一输出 `phase`、`trading_day`、连续竞价状态、轮询窗口、可轮询状态、已交易分钟和原因。
  - naive datetime 按北京时间解释，aware datetime 统一转换到北京时间。
  - 周末和交易日探针确认的节假日统一返回 `closed` 且 `can_poll=false`。
- `backend/app/data_quality.py`
  - 新增不可变 `DataQuality`。
  - 支持按行数覆盖和最近成功观测计算 `FRESH/PARTIAL/STALE/MISSING/INVALID`。
  - 只有完整且未过期结果才是 `usable=true`；其他结果明确 `fail_closed=true`。
  - `to_dict()` 输出稳定 JSON 结构，不依赖 Provider SDK。
- `backend/app/services/minute_refresh.py`
  - `minute-refresh/status` 增加 `market_session` 和 `data_quality`。
  - freshness 阈值复用既有 `max(2 * interval, 30s)` 健康边界。
- `backend/app/services/quote_service.py`
  - `/api/intraday/status` 增加 `market_session` 和 `data_quality`。
  - 原有行情阶段和连续竞价判断收敛到统一市场时段契约。
- `frontend/src/lib/api.ts`
  - 同步分钟刷新和实时行情状态的新质量/时段字段。
- `backend/tests/test_data_quality_session.py`
  - 覆盖北京时间转换、上午/午休/午后边界、周末/节假日、完整/部分/缺失/过期/非法质量状态。

## 验收

- AC result: `PASS`
- MarketSession 覆盖阶段、交易日、轮询窗口和已交易分钟：`YES`
- DataQuality 覆盖 coverage、stale、missing、invalid：`YES`
- 缺失/不完整/过期结果 fail-closed：`YES`
- 确定休市阻止轮询，未知交易日保持兼容：`YES`
- 旧 `market_phase`、`is_trading_hours`、`healthy` 字段保留：`YES`

## 验证

- `backend/.venv/Scripts/python.exe -m pytest ...`：`101 passed`
- `backend/.venv/Scripts/python.exe -m ruff check app/market_time.py app/data_quality.py tests/test_data_quality_session.py ...`：通过
- `git diff --check`：通过
- 前端 `pnpm build`：仍未完成；本地 `node_modules` 重建受 Windows `EPERM`/无 TTY 环境影响。

## 下一任务

`TASK-0201 free-stockdb Bridge / Provider`：先实现最小外部数据源 Bridge，继续保持 Strategy/Backtest 不直接依赖供应商 SDK。
