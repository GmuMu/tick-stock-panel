from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, timedelta

import polars as pl
import pytest

from app.indicators.pipeline import INDICATOR_COLUMNS, compute_indicators
from app.indicators.spec import (
    ALL_INDICATOR_COLUMNS,
    INDICATOR_DEPENDENCIES,
    INDICATOR_SPEC_VERSION,
    INDICATOR_SPECS,
    get_indicator_spec,
    get_indicator_specs,
    resolve_needed,
)
from app.indicators.spec import (
    INDICATOR_COLUMNS as SPEC_INDICATOR_COLUMNS,
)


def _bars(n: int = 90) -> pl.DataFrame:
    rows = []
    for symbol, offset in (("600000.SH", 0.0), ("300001.SZ", 2.0)):
        for index in range(n):
            close = 10.0 + offset + index * 0.03 + ((index % 7) - 3) * 0.04
            rows.append(
                {
                    "symbol": symbol,
                    "date": date(2024, 1, 1) + timedelta(days=index),
                    "open": close - 0.02,
                    "high": close + 0.10,
                    "low": close - 0.10,
                    "close": close,
                    "volume": 1000 + index * 10,
                }
            )
    return pl.DataFrame(rows)


def test_indicator_spec_registry_is_versioned_and_immutable() -> None:
    assert INDICATOR_SPEC_VERSION == "1.0.0"
    assert len(INDICATOR_SPECS) == len(get_indicator_specs())
    assert all(spec.version == INDICATOR_SPEC_VERSION for spec in get_indicator_specs())

    with pytest.raises(FrozenInstanceError):
        get_indicator_spec("ma20").name = "changed"

    with pytest.raises(TypeError):
        INDICATOR_SPECS["ma20"] = get_indicator_spec("ma20")


def test_indicator_spec_names_and_public_columns_are_complete() -> None:
    specs = get_indicator_specs()
    names = [spec.name for spec in specs]

    assert len(names) == len(set(names))
    assert set(names) == ALL_INDICATOR_COLUMNS
    assert {
        spec.name for spec in specs if not spec.internal
    } == SPEC_INDICATOR_COLUMNS
    assert INDICATOR_COLUMNS == SPEC_INDICATOR_COLUMNS
    assert all(not name.startswith("_") for name in SPEC_INDICATOR_COLUMNS)


def test_indicator_spec_dependencies_are_acyclic_and_resolve_transitively() -> None:
    for name, dependencies in INDICATOR_DEPENDENCIES.items():
        assert dependencies <= ALL_INDICATOR_COLUMNS
        assert name not in dependencies

    assert resolve_needed(None) == set(ALL_INDICATOR_COLUMNS)
    assert resolve_needed({"macd_hist"}) == {
        "macd_hist",
        "macd_dea",
        "macd_dif",
        "_ema12",
        "_ema26",
    }
    assert resolve_needed({"atr_14"}) == {"atr_14", "_tr", "prev_close"}
    assert resolve_needed({"vol_ratio_5d"}) == {"vol_ratio_5d", "_vol_ma5_prev"}


def test_indicator_spec_windows_and_warmup_metadata() -> None:
    assert get_indicator_spec("ma60").windows == (60,)
    assert get_indicator_spec("ma60").warmup_bars == 60
    assert get_indicator_spec("macd_hist").windows == (9, 12, 26)
    assert get_indicator_spec("macd_hist").warmup_bars == 26
    assert get_indicator_spec("rsi_14").windows == (14,)
    assert get_indicator_spec("rsi_14").warmup_bars == 14
    assert get_indicator_spec("vol_ratio_5d").windows == (5, 1)
    assert get_indicator_spec("vol_ratio_5d").warmup_bars == 5


def test_spec_driven_public_columns_preserve_indicator_values() -> None:
    bars = _bars()
    full = compute_indicators(bars)
    requested = compute_indicators(bars, needed=set(SPEC_INDICATOR_COLUMNS))

    assert requested.select(sorted(SPEC_INDICATOR_COLUMNS)).equals(
        full.select(sorted(SPEC_INDICATOR_COLUMNS))
    )
