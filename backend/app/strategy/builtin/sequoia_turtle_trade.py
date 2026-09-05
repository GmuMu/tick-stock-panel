"""Sequoia-X TurtleTrade: 20-day breakout with liquidity and bullish close."""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    valid_rolling_max,
    valid_shift,
)

META = {
    "id": "sequoia_turtle_trade",
    "name": "Sequoia TurtleTrade",
    "description": "收盘价突破前20日最高价, 且成交额充足、收阳并高于昨日收盘价",
    "tags": ["Sequoia-X", "海龟", "突破", "量价"],
    "asset_types": ["stock", "etf"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "breakout_window",
            "label": "突破回看窗口",
            "type": "int",
            "default": 20,
            "min": 5,
            "max": 120,
            "step": 1,
        },
        {
            "id": "amount_min",
            "label": "最低成交额",
            "type": "float",
            "default": 100000000.0,
            "min": 0.0,
            "max": 10000000000.0,
            "step": 10000000.0,
        },
    ],
    "scoring": {"momentum_20d": 0.6, "amount_ratio_5d": 0.4},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_sequoia_turtle_breakout"]
EXIT_SIGNALS = []
STOP_LOSS = -0.08
MAX_HOLD_DAYS = 20


class SequoiaTurtleTradeMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "close", "volume", "amount"})

    def required_warmup_bars(self, params: dict) -> int:
        return max(5, int(params.get("breakout_window", 20)))

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        window = max(5, int(params.get("breakout_window", 20)))
        amount = market.field("amount")
        close_valid = np.isfinite(market.close)
        high_valid = close_valid & np.isfinite(market.high)
        previous_high = valid_shift(
            valid_rolling_max(market.high, high_valid, window),
            1,
        )
        previous_close = valid_shift(market.close, 1, close_valid)
        entry = (
            close_valid
            & np.isfinite(market.open)
            & np.isfinite(amount)
            & np.isfinite(previous_high)
            & np.isfinite(previous_close)
            & (market.close > previous_high)
            & (amount > float(params.get("amount_min", 100000000.0)))
            & (market.close > market.open)
            & (market.close > previous_close)
        )
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_sequoia_turtle_breakout",),
        )


MATRIX_STRATEGY = SequoiaTurtleTradeMatrixStrategy()
