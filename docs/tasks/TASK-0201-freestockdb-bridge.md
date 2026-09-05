# TASK-0201 free-stockdb Bridge / Provider

## Task

- Branch: `feat/0101-canonical-contracts` (当前工作树继续开发，未自动提交)
- Scope: 通过最小 HTTP Bridge 接入 free-stockdb 的日 K、分钟 K、Tick 快照和除权因子。
- Rule: Strategy/Backtest 不直接导入 free-stockdb 实现；所有供应商字段和单位转换必须停留在 Provider 边界。

## 实现

- `backend/app/plugins/freestockdb/bridge.py`
  - 新增轻量 HTTP Bridge，不依赖 free-stockdb SDK。
  - 支持常见 `data/rows/items/results/result` JSON 信封和按 symbol 分组响应。
  - 默认连接 `http://127.0.0.1:8000`，支持 `FREE_STOCKDB_URL` 覆盖。
  - 支持 `FREE_STOCKDB_*_PATH` 覆盖各数据集路径，并在默认路径 404 时尝试兼容路径。
  - 提供健康探测；服务不可用时插件灰显，不影响主应用启动。
- `backend/app/plugins/freestockdb/provider.py`
  - 新增 `FreeStockDBProvider`，实现 daily、minute、realtime(Tick)、adj_factor、instruments。
  - 供应商别名、裸代码、交易所后缀、时间戳、分钟时间、成交量和涨跌幅统一转换为 canonical 契约。
  - Bridge 异常向上抛出，交由现有 `ProviderRoute` 记录 fallback provenance。
- `backend/app/plugins/freestockdb/plugin.yaml`
  - 将插件接入内置 loader 和能力矩阵，声明四类数据集。
- `backend/tests/test_freestockdb_provider.py`
  - 覆盖响应信封、按 symbol 分组、404 路径回退、日 K、分钟 K、Tick、除权和标的维表归一化。

## 验收

- AC result: `PASS`
- free-stockdb Bridge 存在且不依赖供应商 SDK：`YES`
- daily/minute/Tick/adj_factor Provider 入口齐全：`YES`
- Strategy/Backtest 无 free-stockdb 直连：`YES`
- 响应信封、字段别名和单位转换有离线测试：`YES`
- 服务不可用时不阻断应用启动：`YES`

## 验证

- `backend/.venv/Scripts/python.exe -m pytest tests/test_freestockdb_provider.py tests/test_data_quality_session.py tests/test_capability_router.py tests/test_capability_matrix.py -q`：`32 passed`
- `backend/.venv/Scripts/python.exe -m ruff check app/plugins/freestockdb tests/test_freestockdb_provider.py`：通过
- `git diff --check`：通过
- 未执行真实 free-stockdb 联调：当前工作区未配置该服务地址，需启动服务后用 `FREE_STOCKDB_URL` 进行 smoke test。

## 下一任务

`TASK-0202 Financial-API Provider / Dataset`：定义 financial canonical schema，并把现有扶摇财务适配纳入正式 Provider 契约。
