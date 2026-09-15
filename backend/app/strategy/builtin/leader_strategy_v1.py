"""龙头战法 V1 — 活跃股池 + 连板触发 + 量价确认。"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
    valid_shift,
)


META = {
    "id": "leader_strategy_v1",
    "name": "龙头战法 V1",
    "description": "涨停连板触发, 叠加涨停基因、涨幅、换手和量比确认, 筛选龙头候选",
    "tags": ["龙头", "涨停", "连板", "接力", "量价"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "require_limit_up",
            "label": "要求当日涨停",
            "type": "bool",
            "default": True,
        },
        {
            "id": "min_boards",
            "label": "最低连板数",
            "type": "int",
            "default": 2,
            "min": 1,
            "max": 10,
            "step": 1,
        },
        {
            "id": "min_limit_count",
            "label": "近60日最少涨停次数",
            "type": "int",
            "default": 3,
            "min": 1,
            "max": 10,
            "step": 1,
        },
        {
            "id": "min_confirmations",
            "label": "量价确认最少项数",
            "type": "int",
            "default": 2,
            "min": 1,
            "max": 3,
            "step": 1,
        },
        {
            "id": "min_change",
            "label": "最低涨幅%",
            "type": "float",
            "default": 5.0,
            "min": 2.0,
            "max": 15.0,
            "step": 0.5,
        },
        {
            "id": "min_turnover",
            "label": "最低换手率%",
            "type": "float",
            "default": 5.0,
            "min": 1.0,
            "max": 20.0,
            "step": 0.5,
        },
        {
            "id": "min_vol_ratio",
            "label": "最低量比",
            "type": "float",
            "default": 1.2,
            "min": 0.5,
            "max": 10.0,
            "step": 0.1,
        },
        {
            "id": "include_broken_board",
            "label": "纳入断板反包",
            "type": "bool",
            "default": False,
        },
    ],
    "scoring": {
        "consecutive_limit_ups": 0.30,
        "limit_up_count_60d": 0.25,
        "change_pct": 0.15,
        "turnover_rate": 0.15,
        "vol_ratio_5d": 0.15,
    },
    "order_by": "score",
    "descending": True,
    "limit": 50,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_limit_up"]
EXIT_SIGNALS = ["signal_ma20_breakdown"]
STOP_LOSS = -0.07
MAX_HOLD_DAYS = 10


class LeaderStrategyV1MatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset(
            {
                "close",
                "volume",
                "turnover_rate",
                "consecutive_limit_ups",
            }
        )

    def required_warmup_bars(self, params: dict) -> int:
        del params
        # 60 日涨停基因 + 量比/均线计算需要的预热。
        return 70

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        consecutive = matrix_feature(market, "consecutive_limit_ups")
        limit_count = matrix_feature(market, "limit_up_count_60d")
        change_pct = matrix_feature(market, "change_pct")
        turnover = matrix_feature(market, "turnover_rate")
        vol_ratio = matrix_feature(market, "vol_ratio_5d")

        if params.get("require_limit_up", True):
            current_limit_up = market.limit_up_locked.astype(bool)
        else:
            current_limit_up = np.ones(market.shape, dtype=bool)

        direct_trigger = consecutive >= int(params.get("min_boards", 2))
        if params.get("include_broken_board", False):
            previous_boards = valid_shift(consecutive, 1)
            two_days_ago_boards = valid_shift(consecutive, 2)
            broken_board_trigger = (
                (consecutive <= 1)
                & (previous_boards == 0)
                & (two_days_ago_boards >= 2)
            )
            trigger = direct_trigger | broken_board_trigger
        else:
            trigger = direct_trigger

        active_gene = limit_count >= int(params.get("min_limit_count", 3))
        confirmations = (
            active_gene.astype(np.int8)
            + (
                turnover >= float(params.get("min_turnover", 5.0))
            ).astype(np.int8)
            + (
                vol_ratio >= float(params.get("min_vol_ratio", 1.2))
            ).astype(np.int8)
        )

        entry = current_limit_up & trigger
        entry &= change_pct >= float(params.get("min_change", 5.0)) / 100.0
        entry &= confirmations >= int(params.get("min_confirmations", 2))

        ma20 = matrix_feature(market, "ma20")
        previous_close = valid_shift(market.close, 1)
        previous_ma20 = valid_shift(ma20, 1)
        exit_ = (market.close < ma20) & (previous_close >= previous_ma20)

        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=tuple(ENTRY_SIGNALS),
            exit_signal_ids=tuple(EXIT_SIGNALS),
        )


MATRIX_STRATEGY = LeaderStrategyV1MatrixStrategy()
