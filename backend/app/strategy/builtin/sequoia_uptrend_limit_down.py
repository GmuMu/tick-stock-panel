"""Sequoia-X UptrendLimitDown: MA20/MA60 uptrend with a high-volume limit-down day."""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
    valid_rolling_mean,
    valid_shift,
)

META = {
    "id": "sequoia_uptrend_limit_down",
    "name": "Sequoia UptrendLimitDown",
    "description": "昨日MA20高于MA60, 今日回撤约9.5%且成交量超过MA20均量2倍",
    "tags": ["Sequoia-X", "趋势", "跌停", "放量"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "limit_down_return",
            "label": "今日回撤阈值",
            "type": "float",
            "default": 0.095,
            "min": 0.05,
            "max": 0.2,
            "step": 0.001,
        },
        {
            "id": "volume_multiple",
            "label": "放量倍数",
            "type": "float",
            "default": 2.0,
            "min": 1.0,
            "max": 10.0,
            "step": 0.1,
        },
    ],
    "scoring": {"momentum_60d": 0.6, "vol_ratio_5d": 0.4},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_sequoia_uptrend_limit_down"]
EXIT_SIGNALS = []
STOP_LOSS = -0.1
MAX_HOLD_DAYS = 10


class SequoiaUptrendLimitDownMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 61

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        close_valid = np.isfinite(market.close)
        volume_valid = close_valid & np.isfinite(market.volume)
        ma20 = matrix_feature(market, "ma20")
        ma60 = matrix_feature(market, "ma60")
        previous_ma20 = valid_shift(ma20, 1)
        previous_ma60 = valid_shift(ma60, 1)
        previous_close = valid_shift(market.close, 1, close_valid)
        volume_ma20 = valid_rolling_mean(market.volume, volume_valid, 20)
        entry = (
            close_valid
            & np.isfinite(market.volume)
            & np.isfinite(previous_close)
            & np.isfinite(previous_ma20)
            & np.isfinite(previous_ma60)
            & np.isfinite(volume_ma20)
            & (previous_ma20 > previous_ma60)
            & (market.close <= previous_close * (1.0 - float(params.get("limit_down_return", 0.095))))
            & (market.volume > volume_ma20 * float(params.get("volume_multiple", 2.0)))
        )
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_sequoia_uptrend_limit_down",),
        )


MATRIX_STRATEGY = SequoiaUptrendLimitDownMatrixStrategy()
