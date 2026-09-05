"""Sequoia-X RpsBreakout: cross-sectional RPS strength near a 120-day high."""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
    valid_rolling_max,
)

META = {
    "id": "sequoia_rps_breakout",
    "name": "Sequoia RpsBreakout",
    "description": "120日收益率横截面RPS不低于90, 且收盘价接近120日高点",
    "tags": ["Sequoia-X", "RPS", "强势", "突破"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "rps_threshold",
            "label": "RPS最低分位",
            "type": "float",
            "default": 0.9,
            "min": 0.5,
            "max": 1.0,
            "step": 0.01,
        },
        {
            "id": "near_high_ratio",
            "label": "距120日高点比例",
            "type": "float",
            "default": 0.9,
            "min": 0.5,
            "max": 1.0,
            "step": 0.01,
        },
    ],
    "scoring": {"momentum_120d": 1.0},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_sequoia_rps_breakout"]
EXIT_SIGNALS = []
STOP_LOSS = -0.1
MAX_HOLD_DAYS = 30


class SequoiaRpsBreakoutMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"high", "close"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 120

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        momentum = matrix_feature(market, "momentum_120d")
        close_valid = np.isfinite(market.close)
        high_valid = close_valid & np.isfinite(market.high)
        high_120 = valid_rolling_max(market.high, high_valid, 120)
        rps = _cross_sectional_percentile(momentum)
        threshold = float(params.get("rps_threshold", 0.9))
        near_high_ratio = float(params.get("near_high_ratio", 0.9))
        entry = (
            close_valid
            & np.isfinite(high_120)
            & np.isfinite(rps)
            & (rps >= threshold)
            & (market.close >= high_120 * near_high_ratio)
        )
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            score=np.nan_to_num(
                rps * np.float32(100.0),
                nan=np.float32(0.0),
            ).astype(np.float32),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_sequoia_rps_breakout",),
        )


def _cross_sectional_percentile(values: np.ndarray) -> np.ndarray:
    """Return an ascending percentile rank for every date, ignoring NaN."""
    source = np.asarray(values, dtype=np.float32)
    result = np.full(source.shape, np.nan, dtype=np.float32)
    for time_id in range(source.shape[0]):
        asset_ids = np.flatnonzero(np.isfinite(source[time_id]))
        if asset_ids.size == 0:
            continue
        order = np.argsort(source[time_id, asset_ids], kind="stable")
        result[time_id, asset_ids[order]] = (
            np.arange(1, asset_ids.size + 1, dtype=np.float32) / asset_ids.size
        )
    return result


MATRIX_STRATEGY = SequoiaRpsBreakoutMatrixStrategy()
