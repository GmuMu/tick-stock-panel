# TASK-0205 Sequoia-X Strategies

## Task

- Branch: `feat/sequoia-x-strategies`
- Scope: 将公开项目 `sngyai/Sequoia-X` 中可由日线 OHLCV 表达的选股公式接入本项目。
- Boundary: 不复制 `baostock`、`akshare`、SQLite 或供应商 SDK；所有策略通过现有 `matrix_native` 协议运行。

## Implemented

新增 6 个内置策略：

- `sequoia_turtle_trade`: 前 20 日高点突破、成交额、收阳和昨日收盘价过滤。
- `sequoia_ma_volume`: MA5 上穿 MA20，且成交量超过 MA20 均量 1.5 倍。
- `sequoia_high_tight_flag`: 40 日宽幅、近 10 日紧缩、位于高位并缩量。
- `sequoia_limit_up_shakeout`: 昨日涨幅不低于 9.5%，今日收阴放量且低点不破昨日收盘。
- `sequoia_uptrend_limit_down`: 昨日 MA20 高于 MA60，今日回撤不低于 9.5% 且放量。
- `sequoia_rps_breakout`: 120 日收益率横截面 RPS 不低于 90%，且接近 120 日高点。

`PrivatePlacement` 暂不接入。它依赖定增公告/公司行为数据，而当前标准数据集没有该字段；在数据契约补齐前保持显式缺口，不伪造筛选结果。

## Acceptance

- [x] 6 个策略由 `StrategyEngine` 自动发现。
- [x] 所有策略使用 `matrix_native`，不直接依赖 Provider SDK。
- [x] 每个策略声明资产类型、日线周期、输入字段和预热窗口。
- [x] 公式触发、关键条件不满足、历史不足和 RPS 横截面排名均有离线测试。
- [x] 普通内置矩阵策略数量由 25 增加到 31。

## Verification

- `backend/.venv/Scripts/python.exe -m pytest tests/test_sequoia_x_strategies.py tests/test_screener_etf.py -q`
- `backend/.venv/Scripts/python.exe -m compileall -q app/strategy/builtin`
- `git diff --check`
