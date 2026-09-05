# TASK-0204 Cross-Provider Golden

## Task

- Branch: `feat/0101-canonical-contracts`
- Scope: 用固定、离线、可重复的跨 Provider fixture 验证字段、单位、复权和报告期口径。
- Rule: golden 测试不依赖真实 API Key、网络或运行中的 free-stockdb 服务。

## 实现

- `backend/tests/fixtures/provider_golden/market.json`
  - 固定 `600519.SH` 的日 K、分钟 K、实时、除权事件和财务报告样例。
  - 同时保留 TickFlow、free-stockdb、扶摇和 generic HTTP provider 的供应商字段形态。
- `backend/tests/test_provider_golden.py`
  - 日 K：验证三源字段别名、原始 OHLC、成交量股转手和成交额元口径一致。
  - 分钟 K：验证 free-stockdb 与声明式 HTTP 源的时间、价格、量额字段一致。
  - 实时：验证 free-stockdb 与扶摇的昨收、涨跌额、百分比小数制和成交量手数一致。
  - 除权：验证 TickFlow/free-stockdb 直接因子与扶摇事件公式推导的单事件因子一致。
  - 财务：验证 TickFlow 与扶摇保留同一 `period_end` 和独立的 `announce_date`。
- `docs/data/DATA_GOLDEN_BASELINE.md`
  - 记录 canonical 规则、字段范围、容差和验收边界。

## 验收

- AC result: `PASS`
- 跨 Provider 字段映射：`YES`
- shares → lots 单位转换：`YES`
- percent → decimal 比例转换：`YES`
- 日 K 原始价与本地前复权边界：`YES`
- 单事件除权因子与非累积语义：`YES`
- `period_end` / `announce_date` 时间可得性边界：`YES`
- 离线、稳定、可重复：`YES`
- Strategy/Backtest 不直接依赖 Provider SDK：`YES`

## 验证

- `backend/.venv/Scripts/python.exe -m pytest tests/test_provider_golden.py -q`：`6 passed`
- `backend/.venv/Scripts/python.exe -m pytest tests/test_provider_golden.py tests/test_canonical_contract.py tests/test_freestockdb_provider.py tests/test_fuyao_provider.py tests/test_fuyao_financial.py tests/test_financial_contract.py tests/test_custom_pct_units.py tests/test_provider_health.py -q`：`132 passed`
- `backend/.venv/Scripts/python.exe -m ruff check tests/test_provider_golden.py`：通过
- `git diff --check`：通过

## 下一任务

`TASK-0301 IndicatorSpec`：抽出可版本化的指标定义、依赖列、窗口和边界规范，不复制现有指标 pipeline。
