"""Sequoia-X HighTightFlag: high-tight-flag consolidation pattern."""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    valid_rolling_max,
    valid_rolling_mean,
    valid_rolling_min,
    valid_shift,
)

META = {
    "id": "sequoia_high_tight_flag",
    "name": "Sequoia HighTightFlag",
    "description": "40日振幅足够大、近10日高位紧缩、且今日缩量",
    "tags": ["Sequoia-X", "旗形", "高位整理", "缩量"],
    "asset_types": ["stock", "etf"],
    "timeframes": ["1d"],
    "scoring": {"momentum_60d": 0.6, "vol_ratio_5d": 0.4},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_sequoia_high_tight_flag"]
EXIT_SIGNALS = []
STOP_LOSS = -0.08
MAX_HOLD_DAYS = 20


class SequoiaHighTightFlagMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"high", "low", "close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 40

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        del params
        close_valid = np.isfinite(market.close)
        high_valid = close_valid & np.isfinite(market.high)
        low_valid = close_valid & np.isfinite(market.low)
        volume_valid = close_valid & np.isfinite(market.volume)

        high_40 = valid_rolling_max(market.high, high_valid, 40)
        low_40 = valid_rolling_min(market.low, low_valid, 40)
        high_10 = valid_rolling_max(market.high, high_valid, 10)
        low_10 = valid_rolling_min(market.low, low_valid, 10)
        previous_volume = valid_shift(market.volume, 1, volume_valid)
        previous_volume_ma20 = valid_rolling_mean(
            previous_volume,
            np.isfinite(previous_volume),
            20,
        )
        entry = (
            close_valid
            & np.isfinite(market.volume)
            & np.isfinite(high_40)
            & np.isfinite(low_40)
            & np.isfinite(high_10)
            & np.isfinite(low_10)
            & np.isfinite(previous_volume_ma20)
            & (high_40 / low_40 > np.float32(1.6))
            & (high_10 / low_10 < np.float32(1.15))
            & (low_10 >= high_40 * np.float32(0.8))
            & (market.volume < previous_volume_ma20 * np.float32(0.6))
        )
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_sequoia_high_tight_flag",),
        )


MATRIX_STRATEGY = SequoiaHighTightFlagMatrixStrategy()
