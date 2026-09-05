"""Sequoia-X MaVolume: bullish MA5/MA20 cross with volume expansion."""

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
    "id": "sequoia_ma_volume",
    "name": "Sequoia MaVolume",
    "description": "昨日MA5低于MA20、今日MA5上穿MA20, 同时成交量超过MA20均量1.5倍",
    "tags": ["Sequoia-X", "均线", "放量", "金叉"],
    "asset_types": ["stock", "etf"],
    "timeframes": ["1d"],
    "scoring": {"change_pct": 0.5, "vol_ratio_5d": 0.5},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_sequoia_ma_volume_cross"]
EXIT_SIGNALS = []
STOP_LOSS = -0.08
MAX_HOLD_DAYS = 20


class SequoiaMaVolumeMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 20

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        del params
        ma5 = matrix_feature(market, "ma5")
        ma20 = matrix_feature(market, "ma20")
        previous_ma5 = valid_shift(ma5, 1)
        previous_ma20 = valid_shift(ma20, 1)
        volume_valid = np.isfinite(market.close) & np.isfinite(market.volume)
        volume_ma20 = valid_rolling_mean(market.volume, volume_valid, 20)
        entry = (
            np.isfinite(market.close)
            & np.isfinite(market.volume)
            & np.isfinite(previous_ma5)
            & np.isfinite(previous_ma20)
            & np.isfinite(ma5)
            & np.isfinite(ma20)
            & np.isfinite(volume_ma20)
            & (previous_ma5 < previous_ma20)
            & (ma5 > ma20)
            & (market.volume > volume_ma20 * np.float32(1.5))
        )
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_sequoia_ma_volume_cross",),
        )


MATRIX_STRATEGY = SequoiaMaVolumeMatrixStrategy()
