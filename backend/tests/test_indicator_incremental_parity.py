from __future__ import annotations

from datetime import date, timedelta

import polars as pl
from polars.testing import assert_frame_equal

from app.indicators.pipeline import compute_enriched, compute_enriched_today, compute_indicators
from app.tickflow.repository import DataStore, KlineRepository


def _history(rows: int = 100) -> pl.DataFrame:
    records = []
    for index in range(rows):
        close = 10.0 + index * 0.1 + ((index % 5) - 2) * 0.03
        volume = 1000.0 + index * 10.0
        records.append(
            {
                "symbol": "600000.SH",
                "date": date(2026, 1, 1) + timedelta(days=index),
                "open": close - 0.03,
                "high": close + 0.10,
                "low": close - 0.10,
                "close": close,
                "volume": volume,
                "amount": close * volume,
            }
        )
    return pl.DataFrame(records)


def test_incremental_indicator_values_match_batch_for_same_history(tmp_path) -> None:
    history = _history()
    history_enriched = compute_indicators(history).with_columns(
        pl.lit(0, dtype=pl.UInt32).alias("consecutive_limit_ups"),
        pl.lit(0, dtype=pl.UInt32).alias("consecutive_limit_downs"),
    )

    repo = KlineRepository(DataStore(tmp_path))
    repo._enriched_history_cache = history_enriched
    repo._enriched_history_start = history_enriched["date"].min()
    repo._build_live_agg(history["date"][-1])

    today_close = 20.5
    today = pl.DataFrame(
        {
            "symbol": ["600000.SH"],
            "date": [date(2026, 4, 11)],
            "open": [today_close - 0.03],
            "high": [today_close + 0.10],
            "low": [today_close - 0.10],
            "close": [today_close],
            "volume": [2200.0],
            "amount": [today_close * 2200.0],
        }
    )
    incremental = compute_enriched_today(
        repo.get_live_agg(),
        history_enriched.tail(1),
        today,
    )
    batch = compute_enriched(history.vstack(today)).tail(1)

    common = sorted(set(incremental.columns) & set(batch.columns))
    assert_frame_equal(
        incremental.select(common),
        batch.select(common),
        check_exact=False,
        rel_tol=1e-10,
        abs_tol=1e-10,
    )
