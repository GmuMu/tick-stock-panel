"""Sequoia-X multi-period RPS signal strategy.

This mirrors the reference project's three-period RPS rules while keeping the
existing matrix-native execution contract.  RPS is calculated cross-sectionally
for each trading date from 20/120/250-day returns.
"""
from __future__ import annotations

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
)

META = {
    "id": "sequoia_rps_multi_period",
    "name": "Sequoia 多周期RPS突破",
    "description": "短中长期RPS联合过滤，识别趋势底色良好且短期刚启动的强势股",
    "tags": ["Sequoia-X", "RPS", "多周期", "趋势"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "long_rps_min",
            "label": "长期RPS底线",
            "type": "float",
            "default": 70.0,
            "min": 0.0,
            "max": 100.0,
            "step": 1.0,
        },
        {
            "id": "mid_rps_min",
            "label": "中期RPS底线",
            "type": "float",
            "default": 80.0,
            "min": 0.0,
            "max": 100.0,
            "step": 1.0,
        },
        {
            "id": "short_rps_low",
            "label": "短期RPS下限",
            "type": "float",
            "default": 60.0,
            "min": 0.0,
            "max": 100.0,
            "step": 1.0,
        },
        {
            "id": "short_rps_high",
            "label": "短期RPS上限",
            "type": "float",
            "default": 90.0,
            "min": 0.0,
            "max": 100.0,
            "step": 1.0,
        },
        {
            "id": "no_touch_long_min",
            "label": "长期RPS最低过滤",
            "type": "float",
            "default": 50.0,
            "min": 0.0,
            "max": 100.0,
            "step": 1.0,
        },
    ],
    "scoring": {},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_sequoia_rps_multi_period"]
EXIT_SIGNALS = []
STOP_LOSS = -0.1
MAX_HOLD_DAYS = 30


class SequoiaRpsMultiPeriodMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"close"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 250

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        short_rps = _cross_sectional_percentile(
            matrix_feature(market, "momentum_20d")
        )
        mid_rps = _cross_sectional_percentile(
            matrix_feature(market, "momentum_120d")
        )
        long_rps = _cross_sectional_percentile(
            matrix_feature(market, "momentum_250d")
        )

        finite = (
            np.isfinite(short_rps)
            & np.isfinite(mid_rps)
            & np.isfinite(long_rps)
        )
        long_min = float(params.get("long_rps_min", 70.0))
        mid_min = float(params.get("mid_rps_min", 80.0))
        short_low = float(params.get("short_rps_low", 60.0))
        short_high = float(params.get("short_rps_high", 90.0))
        no_touch_long_min = float(params.get("no_touch_long_min", 50.0))

        firework = (short_rps >= 95.0) & (mid_rps < 70.0)
        weak_turn = (short_rps < 40.0) & (mid_rps < 60.0)
        entry = finite & (long_rps >= no_touch_long_min) & ~firework & ~weak_turn

        score = (
            short_rps * np.float32(0.20)
            + mid_rps * np.float32(0.50)
            + long_rps * np.float32(0.30)
        )
        true_breakout = (
            (long_rps >= long_min)
            & (mid_rps >= mid_min)
            & (short_rps >= short_low)
            & (short_rps <= short_high)
        )
        score = np.where(true_breakout, score + np.float32(10.0), score)
        score = np.where(
            (short_rps >= 95.0) & (mid_rps < 80.0),
            score - np.float32(20.0),
            score,
        )
        score = np.where(
            (short_rps >= 95.0)
            & (mid_rps >= 95.0)
            & (long_rps >= 95.0),
            score - np.float32(10.0),
            score,
        )
        score = np.nan_to_num(
            np.where(finite, score, np.nan),
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        ).astype(np.float32)

        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            score=score,
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_sequoia_rps_multi_period",),
        )


def _cross_sectional_percentile(values: np.ndarray) -> np.ndarray:
    """Return an ascending 0-100 percentile rank for each date."""
    source = np.asarray(values, dtype=np.float32)
    result = np.full(source.shape, np.nan, dtype=np.float32)
    for time_id in range(source.shape[0]):
        asset_ids = np.flatnonzero(np.isfinite(source[time_id]))
        if asset_ids.size == 0:
            continue
        values_for_date = source[time_id, asset_ids]
        order = np.argsort(values_for_date, kind="stable")
        sorted_values = values_for_date[order]
        _, first_positions, counts = np.unique(
            sorted_values,
            return_index=True,
            return_counts=True,
        )
        average_ranks = (
            first_positions.astype(np.float32)
            + (counts.astype(np.float32) + np.float32(1.0)) / np.float32(2.0)
        ) / np.float32(asset_ids.size) * np.float32(100.0)
        rank_by_sorted_position = np.repeat(average_ranks, counts)
        result[time_id, asset_ids[order]] = rank_by_sorted_position
    return result


MATRIX_STRATEGY = SequoiaRpsMultiPeriodMatrixStrategy()
