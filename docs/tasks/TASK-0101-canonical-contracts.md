# TASK-0101 Canonical Symbol / Date / Unit Contract

## Task

- Branch: `feat/0101-canonical-contracts`
- Scope: 在 Provider 归一化边界建立统一的代码、日期、时间戳和数值单位口径。
- Rule: 不改变既有 Fuyao/StockSDK 实时专属转换；先统一可复用边界函数，再由现有 normalizer 接入。

## 实现

- `backend/app/data_providers/schemas.py`
  - `normalize_symbol`: 常见 `SH/SSE/SHSE`、`SZ/SZSE`、`BJ/BSE` 统一为 `CODE.EXCHANGE`。
  - `normalize_date`: `YYYYMMDD`、日期、日期时间和毫秒时间戳统一按北京时间归属到 `date`。
  - `normalize_epoch_ms`: 时间戳统一为 Unix epoch milliseconds；无时区 datetime 按北京时间解释。
  - `normalize_price`、`normalize_ratio`、`normalize_volume`、`normalize_amount`：显式单位转换，非法或非有限值返回空值。
  - `CanonicalQuoteMeta`: 不可变地保存 `symbol`、`trade_date`、`quote_ts`、`received_at`，并提供独立的 `quote_trade_day`。
- `backend/app/data_providers/normalizer.py`
  - daily、除权因子和 instrument 入口复用 canonical symbol/date/time/unit 转换。
  - 保留旧字段别名和输出列，兼容已有 provider 调用方。
- `backend/tests/test_canonical_contract.py`
  - 覆盖代码格式、北京时间跨日、报价归属日分离、单位转换、空值和 daily/instrument 入口。

## 验证

- 新契约及受影响回归：`135 passed, 1 deselected`
- `ruff check app/data_providers/schemas.py app/data_providers/normalizer.py tests/test_canonical_contract.py`：通过
- `git diff --check`：通过
- 已知环境问题：既有 `test_bridge_mjs_resolves_local_sdk_and_maps_realtime_timestamp` 在 Windows 临时目录触发 Node `EPERM`，与本任务改动无关，因此定向回归中单独 deselect；不宣称该环境测试通过。

## 验收

- AC result: `PASS`
- Provider daily、adj_factor、instrument 归一化共用 canonical 边界：`YES`
- `trade_date` 与 `quote_trade_day` 分离：`YES`
- 下一任务：`TASK-0102 Data Capability Matrix`
