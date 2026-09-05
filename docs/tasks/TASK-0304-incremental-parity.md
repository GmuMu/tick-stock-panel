# TASK-0304 Incremental Parity

## Task

- Branch: `feat/0301-indicator-spec`
- Scope: 证明盘后 batch 与盘中 incremental 对同一历史窗口和今日 K 线给出一致指标结果。
- Boundary: 不取消盘中增量性能优化；只修正状态窗口、统计口径和递推边界，使增量路径复用 batch 的指标语义。

## Findings And Fixes

- `backend/app/tickflow/repository.py`
  - live aggregation 使用历史缓存的完整可用范围计算 EMA/RSI 状态，避免从 60 日截断窗口重新播种。
  - `high_60d/low_60d` 的滚动状态改为基于 close，与 batch 指标定义一致。
- `backend/app/indicators/pipeline.py`
  - incremental BOLL 标准差改为样本标准差，与 Polars batch `rolling_std` 对齐。
  - incremental 年化波动率使用同一套 20 日样本方差口径。
  - incremental 60 日极值使用 close，而不是当日 high/low。
- `backend/tests/test_indicator_incremental_parity.py`
  - 构造固定 100 根历史日线和 1 根今日 K 线。
  - 通过真实 `KlineRepository._build_live_agg()` 生成递推状态。
  - 对 incremental 与 batch 的共同输出逐列比较。

## Acceptance

- [x] EMA、RSI 等递推指标不会因状态窗口截断而重新播种。
- [x] BOLL、年化波动率的样本标准差口径一致。
- [x] 60 日极值的 close 口径一致。
- [x] 同一输入的 batch/incremental 共同输出在容差内一致。
- [x] 不改变实时路径对无历史、复牌和停牌行的既有处理。

## Verification

- `backend/.venv/Scripts/python.exe -m pytest tests/test_indicator_incremental_parity.py tests/test_realtime_enriched_resume.py tests/test_live_enriched_metadata.py tests/test_enriched_full_rebuild.py tests/test_price_levels_contract.py tests/test_indicator_golden.py tests/test_indicator_spec.py tests/test_indicator_needed.py -q`：`31 passed`
- `backend/.venv/Scripts/python.exe -m pytest tests/test_indicator_incremental_parity.py -q`：`1 passed`
- `backend/.venv/Scripts/ruff.exe check tests/test_indicator_incremental_parity.py`：通过
- `git diff --check`：通过

## Next Task

按 GAP Matrix 进入 Phase 4：`TASK-0401 Strategy Contract`。
