# TASK-0403 EOD Seeds

## Task

- Branch: `feat/0301-indicator-spec`
- Scope: 保存每日盘后策略候选种子，固定交易日期、输入质量、版本和来源。
- Boundary: 使用本地原子 JSON 存储，不把运行数据写入 Git；不替换既有策略缓存。

## Implemented

- `backend/app/services/eod_seeds.py`
  - 以 `user_data/eod_seeds.json` 保存候选批次。
  - 写入采用临时文件加 `os.replace`，并限制保留最近 500 个 seed。
  - 相同 `seed_id` 重复写入幂等；同 ID 内容不一致时拒绝覆盖并报告冲突。
- `backend/app/api/strategy.py`
  - `GET /api/strategies/seeds` 支持按策略和日期查询。
- 候选 seed 固化 `model_version`、`strategy_version`、`as_of`、候选、执行 provenance 和 `DataQuality`。

## Acceptance

- [x] seed ID 对同一策略、日期和版本稳定。
- [x] 同一 seed 重跑不会产生重复记录。
- [x] seed 内容冲突时 fail-closed，不静默覆盖历史证据。
- [x] 日期、候选、来源和数据质量均可通过 API 查询。

## Verification

- `backend/.venv/Scripts/python.exe -m pytest tests/test_phase4_execution.py -q`: `9 passed`。
- 覆盖原子存储、幂等、冲突、日期过滤和 API 查询。
- `git diff --check`: 通过。

## Next Task

按 GAP Matrix 进入 `TASK-0404 EOD Runner`。
