"""威科夫吸筹策略:区间蓄势、Spring 测试与 SOS 放量突破。"""

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
    "id": "wyckoff_accumulation",
    "name": "威科夫吸筹突破",
    "description": "识别窄幅吸筹区间及 Spring 洗盘,以 SOS 放量突破确认入场,支撑失守退出",
    "tags": ["威科夫", "吸筹", "Spring", "SOS", "量价"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "range_days",
            "label": "吸筹区间天数",
            "type": "int",
            "default": 20,
            "min": 10,
            "max": 60,
            "step": 1,
        },
        {
            "id": "range_pct_max",
            "label": "区间振幅上限%",
            "type": "float",
            "default": 15.0,
            "min": 5.0,
            "max": 30.0,
            "step": 0.5,
        },
        {
            "id": "sos_volume_ratio",
            "label": "SOS最低量比",
            "type": "float",
            "default": 1.3,
            "min": 1.0,
            "max": 5.0,
            "step": 0.1,
        },
        {
            "id": "spring_lookback",
            "label": "Spring回看天数",
            "type": "int",
            "default": 10,
            "min": 0,
            "max": 30,
            "step": 1,
        },
        {
            "id": "require_spring",
            "label": "要求近期出现Spring",
            "type": "bool",
            "default": False,
        },
    ],
    "scoring": {},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_wyckoff_sos"]
EXIT_SIGNALS = ["signal_wyckoff_support_breakdown"]
STOP_LOSS = -0.07
MAX_HOLD_DAYS = 30


class WyckoffAccumulationMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        return max(10, int(params.get("range_days", 20))) + 5

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        days = max(10, int(params.get("range_days", 20)))
        spring_lookback = max(0, int(params.get("spring_lookback", 10)))
        valid_ohlc = (
            np.isfinite(market.open)
            & np.isfinite(market.high)
            & np.isfinite(market.low)
            & np.isfinite(market.close)
        )
        valid_volume = valid_ohlc & np.isfinite(market.volume)

        prior_high = valid_shift(
            valid_rolling_max(market.high, valid_ohlc, days),
            1,
            valid_ohlc,
        )
        prior_low = valid_shift(
            valid_rolling_min(market.low, valid_ohlc, days),
            1,
            valid_ohlc,
        )
        prior_volume_average = valid_shift(
            valid_rolling_mean(market.volume, valid_volume, days),
            1,
            valid_volume,
        )
        range_pct = np.divide(
            (prior_high - prior_low) * np.float32(100.0),
            market.close,
            out=np.full(market.shape, np.nan, dtype=np.float32),
            where=np.isfinite(market.close) & (market.close > 0),
        )
        volume_ratio = np.divide(
            market.volume,
            prior_volume_average,
            out=np.full(market.shape, np.nan, dtype=np.float32),
            where=np.isfinite(prior_volume_average) & (prior_volume_average > 0),
        )

        spring = (
            valid_volume
            & np.isfinite(prior_low)
            & np.isfinite(prior_volume_average)
            & (market.low < prior_low)
            & (market.close > prior_low)
            & (market.close > market.open)
            & (market.volume <= prior_volume_average * np.float32(1.3))
        )
        recent_spring = spring
        for offset in range(1, spring_lookback + 1):
            recent_spring |= valid_shift(
                spring.astype(np.float32),
                offset,
                valid_ohlc,
            ) > 0

        sos = (
            valid_volume
            & np.isfinite(prior_high)
            & np.isfinite(range_pct)
            & np.isfinite(volume_ratio)
            & (range_pct <= float(params.get("range_pct_max", 15.0)))
            & (market.close > prior_high)
            & (market.close > market.open)
            & (volume_ratio >= float(params.get("sos_volume_ratio", 1.3)))
        )
        if params.get("require_spring", False):
            sos &= recent_spring

        support_breakdown = (
            valid_ohlc
            & np.isfinite(prior_low)
            & (market.close < prior_low)
        )
        score = np.nan_to_num(
            volume_ratio + recent_spring.astype(np.float32) * np.float32(0.5),
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        ).astype(np.float32)
        return make_signal_matrix(
            market.shape,
            entry=sos.astype(np.uint8),
            exit=support_breakdown.astype(np.uint8),
            score=score,
            entry_signal_code=np.where(sos, 0, -1).astype(np.int16),
            exit_signal_code=np.where(support_breakdown, 0, -1).astype(np.int16),
            entry_signal_ids=tuple(ENTRY_SIGNALS),
            exit_signal_ids=tuple(EXIT_SIGNALS),
        )


MATRIX_STRATEGY = WyckoffAccumulationMatrixStrategy()
