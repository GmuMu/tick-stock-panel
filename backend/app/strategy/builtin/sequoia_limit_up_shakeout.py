"""Sequoia-X LimitUpShakeout: limit-up day followed by a bullish shakeout."""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    valid_shift,
)

META = {
    "id": "sequoia_limit_up_shakeout",
    "name": "Sequoia LimitUpShakeout",
    "description": "昨日接近涨停, 今日收阴放量, 但最低价不跌破昨日收盘价",
    "tags": ["Sequoia-X", "涨停", "洗盘", "放量"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "limit_up_return",
            "label": "昨日涨幅阈值",
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
    "scoring": {},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_sequoia_limit_up_shakeout"]
EXIT_SIGNALS = []
STOP_LOSS = -0.08
MAX_HOLD_DAYS = 10


class SequoiaLimitUpShakeoutMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "low", "close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 2

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        close_valid = np.isfinite(market.close)
        volume_valid = close_valid & np.isfinite(market.volume)
        previous_close = valid_shift(market.close, 1, close_valid)
        two_days_ago_close = valid_shift(market.close, 2, close_valid)
        previous_volume = valid_shift(market.volume, 1, volume_valid)
        entry = (
            close_valid
            & np.isfinite(market.open)
            & np.isfinite(market.low)
            & np.isfinite(market.volume)
            & np.isfinite(previous_close)
            & np.isfinite(two_days_ago_close)
            & np.isfinite(previous_volume)
            & (
                previous_close
                >= two_days_ago_close
                * (1.0 + float(params.get("limit_up_return", 0.095)))
            )
            & (market.close < market.open)
            & (market.volume > previous_volume * float(params.get("volume_multiple", 2.0)))
            & (market.low >= previous_close)
        )
        drop_pct = np.full(market.shape, np.nan, dtype=np.float32)
        np.divide(
            previous_close - market.close,
            previous_close,
            out=drop_pct,
            where=np.isfinite(previous_close) & (previous_close > 0),
        )
        volume_ratio = np.full(market.shape, np.nan, dtype=np.float32)
        np.divide(
            market.volume,
            previous_volume,
            out=volume_ratio,
            where=np.isfinite(market.volume) & np.isfinite(previous_volume) & (previous_volume > 0),
        )
        score = np.full(market.shape, np.nan, dtype=np.float32)
        np.divide(
            volume_ratio,
            np.maximum(drop_pct, np.float32(0.001)),
            out=score,
            where=np.isfinite(volume_ratio) & np.isfinite(drop_pct),
        )
        score = np.nan_to_num(score, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            score=score,
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_sequoia_limit_up_shakeout",),
        )


MATRIX_STRATEGY = SequoiaLimitUpShakeoutMatrixStrategy()
