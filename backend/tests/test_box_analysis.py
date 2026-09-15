from datetime import date, timedelta

import polars as pl

from app.services.box_analysis import analyze_box, analyze_box_batch
from app.services.chan_analysis import (
    _Bi,
    _Fractal,
    _strict_cbsp_points,
    analyze_chan,
)


def _bars(count: int = 70, *, breakout: bool = False) -> pl.DataFrame:
    start = date(2026, 1, 2)
    rows = []
    for index in range(count):
        close = 10.0 + (index % 4) * 0.05
        high = close + 0.2
        low = close - 0.2
        volume = 1000.0
        if breakout and index == count - 1:
            close = 10.8
            high = 11.0
            low = 10.5
            volume = 2400.0
        rows.append({
            "date": start + timedelta(days=index),
            "open": close - 0.05,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": volume * close,
        })
    return pl.DataFrame(rows)


def test_analyze_box_returns_current_boundaries_and_score():
    result = analyze_box(_bars(), symbol="000001.SZ", lookback=60)

    assert result["symbol"] == "000001.SZ"
    assert result["box"]["upper"] > result["box"]["lower"]
    assert result["box"]["status"] == "inside"
    assert result["volume"]["ratio"] == 1.0
    assert result["score"] is not None
    assert len(result["recent"]) > 0
    assert len(result["box_series"]) == 10
    assert result["box_series"][0]["date"] < result["box_series"][-1]["date"]


def test_analyze_box_detects_upward_breakout_with_volume():
    result = analyze_box(_bars(breakout=True), symbol="000001.SZ", lookback=60)

    assert result["box"]["breakout_up"] is True
    assert result["box"]["status_label"] == "向上突破"
    assert result["volume"]["confirmed"] is True
    assert result["score"] >= 25
    assert result["box_series"][-1]["volume_confirmed"] is True
    assert result["box_series"][-1]["breakout_up"] is True


def test_analyze_box_degrades_without_history():
    result = analyze_box(_bars(10), symbol="000001.SZ", lookback=60)

    assert result["box"] is None
    assert result["score"] is None
    assert result["box_series"] == []
    assert "至少需要" in result["message"]


def test_analyze_box_does_not_use_current_bar_for_boundaries():
    frame = _bars(70)
    frame = frame.with_columns(
        pl.when(pl.col("date") == date(2026, 3, 12))
        .then(pl.lit(99.0))
        .otherwise(pl.col("high"))
        .alias("high"),
    )

    result = analyze_box(frame, symbol="000001.SZ", lookback=60)

    assert result["box"]["upper"] < 20
    assert result["box_series"][-1]["upper"] < 20


def test_analyze_box_batch_preserves_symbol_order_and_handles_missing_data():
    result = analyze_box_batch(
        {
            "000001.SZ": _bars(),
            "600000.SH": pl.DataFrame(),
        },
        lookback=60,
    )

    assert list(result) == ["000001.SZ", "600000.SH"]
    assert result["000001.SZ"]["box"] is not None
    assert result["600000.SH"]["box"] is None


def test_analyze_chan_returns_fractals_bis_and_zones():
    rows = []
    start = date(2026, 1, 2)
    closes = [10, 11, 12, 11, 10, 9, 10, 11, 12, 11, 10, 11, 13, 12, 14]
    for index, close in enumerate(closes):
        rows.append({
            "date": start + timedelta(days=index),
            "open": close - 0.2,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "volume": 1000 + index * 50,
        })
    result = analyze_chan(pl.DataFrame(rows), symbol="000001.SZ")

    assert result["symbol"] == "000001.SZ"
    assert result["bars"] == len(closes)
    assert result["merged_bar_count"] > 0
    assert len(result["fractals"]) >= 2
    assert len(result["bis"]) >= 1
    assert isinstance(result["zones"], list)
    assert len(result["macd"]["hist"]) == len(closes)
    assert len(result["moving_averages"]["ma5"]) == len(closes)
    assert len(result["channel"]["upper"]) == len(closes)
    assert len(result["rsi"]["values"]) == len(closes)
    assert len(result["kdj"]["k"]) == len(closes)
    assert len(result["kdj"]["d"]) == len(closes)
    assert len(result["kdj"]["j"]) == len(closes)
    assert len(result["demark"]["setup"]) == len(closes)
    assert len(result["demark"]["countdown"]) == len(closes)
    assert isinstance(result["eigen"], list)
    assert isinstance(result["trendlines"], list)
    assert isinstance(result["segment_signals"], list)
    assert isinstance(result["segment_zones"], list)
    assert result["timeframes"] == ["1d", "1w", "1M"]
    assert set(result["multi_level"]) <= {"1w", "1M"}
    assert isinstance(result["interval_nesting"], list)
    assert isinstance(result["cbsp_points"], list)
    assert isinstance(result["signals"], list)


def test_analyze_chan_builds_weekly_monthly_levels_without_future_dates():
    rows = []
    start = date(2025, 1, 2)
    for index in range(280):
        wave = ((index // 7) % 8) * 0.3
        close = 10.0 + wave + (0.12 if index % 3 else -0.08)
        rows.append({
            "date": start + timedelta(days=index),
            "open": close - 0.05,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000 + index,
        })

    result = analyze_chan(pl.DataFrame(rows), symbol="000001.SZ")

    assert set(result["multi_level"]) == {"1w", "1M"}
    daily_latest = result["as_of"]
    for timeframe, higher in result["multi_level"].items():
        assert higher["as_of"] <= daily_latest
        assert higher["timeframes"] == ["1d"]
        for zone in higher["zones"]:
            assert zone["end_date"] <= daily_latest
        assert timeframe in {"1w", "1M"}


def test_strict_cbsp_requires_divergence_and_reversal_confirmation():
    start = date(2026, 1, 2)
    rows = [
        {"date": start + timedelta(days=index), "close": 10.0, "high": 10.2, "low": 9.8}
        for index in range(30)
    ]
    dates = [start + timedelta(days=index) for index in (2, 7, 12, 18)]
    prices = [12.0, 9.0, 11.0, 11.5]
    directions = ["down", "up", "down", "up"]
    lows = [11.0, 8.0, 10.0, 10.5]
    highs = [12.5, 9.5, 11.5, 12.0]
    bis = []
    for index, (current_date, price, direction, low, high) in enumerate(
        zip(dates, prices, directions, lows, highs, strict=True)
    ):
        kind = "bottom" if direction == "up" else "top"
        fractal = _Fractal(index=index * 5 + 2, kind=kind, date=current_date.isoformat(), price=price)
        bis.append(_Bi(index=index, start=fractal, end=fractal, direction=direction, high=high, low=low))

    macd = {"hist": [0.0] * 30}
    macd["hist"][2] = -2.0
    macd["hist"][12] = -0.8
    points = _strict_cbsp_points(bis, [], macd, rows)

    assert len(points) == 1
    assert points[0]["type"] == "B1"
    assert points[0]["basis"] == "divergence_reversal"


def test_analyze_chan_exposes_demark_setup_and_oscillator_signals():
    start = date(2026, 1, 2)
    rows = []
    for index in range(45):
        close = 10.0 + index * 0.15 if index < 18 else 12.7 - (index - 18) * 0.2
        rows.append({
            "date": start + timedelta(days=index),
            "open": close - 0.05,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000 + index * 10,
        })

    result = analyze_chan(pl.DataFrame(rows), symbol="000001.SZ")

    assert 9 in result["demark"]["setup"] or -9 in result["demark"]["setup"]
    assert all(item["type"].startswith(("demark_", "rsi_", "kdj_"))
               for item in [*result["demark"]["signals"], *result["rsi"]["signals"], *result["kdj"]["signals"]])


def test_analyze_chan_degrades_without_required_columns():
    result = analyze_chan(pl.DataFrame({"date": [date(2026, 1, 2)]}), symbol="000001.SZ")

    assert result["bars"] == 0
    assert result["bis"] == []
    assert "暂无" in result["message"]


def test_analyze_chan_keeps_original_dates_after_inclusion_merge():
    rows = []
    start = date(2026, 1, 2)
    values = [
        (10.0, 9.0),
        (11.0, 8.0),  # 包含前一根, 会被合并
        (12.0, 10.0),
        (11.0, 9.0),
        (9.0, 7.0),
        (10.0, 8.0),
        (13.0, 11.0),
    ]
    for index, (high, low) in enumerate(values):
        close = (high + low) / 2
        rows.append({
            "date": start + timedelta(days=index),
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000,
        })

    result = analyze_chan(pl.DataFrame(rows), symbol="000001.SZ")

    assert result["merged_bar_count"] < len(values)
    for item in result["bis"]:
        assert item["start_date"] in {row["date"].isoformat() for row in rows}
        assert item["end_date"] in {row["date"].isoformat() for row in rows}
