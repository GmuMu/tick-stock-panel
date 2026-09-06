from datetime import date, timedelta

import polars as pl

from app.services.box_analysis import analyze_box, analyze_box_batch


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
