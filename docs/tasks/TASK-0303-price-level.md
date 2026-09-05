# TASK-0303 Price Level

## Task

- Branch: `feat/0301-indicator-spec`
- Scope: 统一关键价位的 OHLC 价格口径、复权语义和缺失质量状态。
- Boundary: 保留现有价位算法；只补输入契约、fail-closed 边界和 API/AI provenance，不引入第二套价位引擎。

## Implemented

- `backend/app/indicators/levels.py`
  - 声明价位计算所需的 `high/low/close` 输入列。
  - 明确 enriched 数据使用 adjusted OHLC，原始 `raw_*` 仅作为 provenance，不参与价位计算。
  - 新增 `level_price_basis()`，区分 `adjusted_ohlc` 与 `canonical_ohlc`。
  - 新增 `level_data_quality()`，统一输出 `FRESH/PARTIAL/MISSING/INVALID`。
  - 缺失或部分 OHLC 时 `compute_levels()` fail-closed，不生成伪价位。
- `backend/app/api/stock_analysis.py`
  - `/api/stock-analysis/levels` 返回 `price_basis` 和 `data_quality`。
  - 空数据返回 `MISSING`，不再只返回无法解释的空数组。
- `backend/app/services/stock_analyzer.py`
  - AI 分析 `meta` 事件同步返回价位价格基准和数据质量。
- `backend/tests/test_price_levels_contract.py`
  - 覆盖 adjusted/raw 口径隔离、完整/部分/缺失 OHLC、空数据 API 和 canonical fallback。

## Acceptance

- [x] 价位计算明确使用 adjusted `open/high/low/close`。
- [x] 改变 `raw_*` 不会改变价位结果。
- [x] 缺失或部分 OHLC 不生成价位，并返回统一质量状态。
- [x] `/levels` 和 AI meta 暴露 `price_basis` 与 `data_quality`。
- [x] 现有价位算法和相关回归保持通过。

## Verification

- `backend/.venv/Scripts/python.exe -m pytest tests/test_price_levels_contract.py tests/test_ai_analysis_focus.py tests/test_indicator_golden.py tests/test_indicator_spec.py tests/test_indicator_needed.py tests/test_baseline_harness.py -q`：`28 passed`
- `backend/.venv/Scripts/ruff.exe check app/api/stock_analysis.py app/services/stock_analyzer.py tests/test_price_levels_contract.py --select I,F,E,N,UP,B,SIM --ignore E501`：通过
- `python -m compileall`：通过
- `git diff --check`：通过

## Next Task

`TASK-0304 Incremental Parity`：证明盘后 batch 与盘中 incremental 的指标结果一致。
