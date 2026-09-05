"""Canonical market-data contract tests.

The provider boundary uses one symbol format, Beijing trade dates, UTC epoch
milliseconds, decimal ratios, CNY prices/amounts, and share-lot volumes.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import polars as pl
import pytest

from app.data_providers.normalizer import (
    normalize_adj_factors,
    normalize_daily,
    normalize_instruments,
)
from app.data_providers.schemas import (
    CanonicalQuoteMeta,
    normalize_amount,
    normalize_date,
    normalize_epoch_ms,
    normalize_price,
    normalize_ratio,
    normalize_symbol,
    normalize_volume,
)


def test_symbol_contract_normalizes_exchange_aliases_without_guessing_unknown_codes():
    assert normalize_symbol(" sh.600000 ") == "600000.SH"
    assert normalize_symbol("000001-szse") == "000001.SZ"
    assert normalize_symbol("BJ830001") == "830001.BJ"
    assert normalize_symbol("custom-code") == "CUSTOM-CODE"
    assert normalize_symbol("  ") is None


def test_date_contract_uses_beijing_calendar_for_aware_values_and_epoch_ms():
    beijing = timezone(timedelta(hours=8))
    assert normalize_date(datetime(2026, 9, 3, 23, 30, tzinfo=UTC)) == date(2026, 9, 4)
    assert normalize_date(datetime(2026, 9, 4, 9, 30, tzinfo=beijing)) == date(2026, 9, 4)
    assert normalize_date("2026-09-04T09:30:00") == date(2026, 9, 4)
    assert normalize_date("20260904") == date(2026, 9, 4)
    assert normalize_date(20260904) == date(2026, 9, 4)
    assert normalize_date(1788485400000) == date(2026, 9, 4)
    assert normalize_date("") is None


def test_quote_meta_keeps_trade_date_separate_from_quote_trade_day():
    quote_ts = int(datetime(2026, 9, 4, 1, 30, tzinfo=UTC).timestamp() * 1000)
    received_at = datetime(2026, 9, 4, 1, 31, tzinfo=UTC)
    meta = CanonicalQuoteMeta(
        symbol="sh.600000",
        trade_date="2026-09-03",
        quote_ts=quote_ts,
        received_at=received_at,
    )

    assert meta.symbol == "600000.SH"
    assert meta.trade_date == date(2026, 9, 3)
    assert meta.quote_trade_day == date(2026, 9, 4)
    assert meta.quote_ts == quote_ts
    assert meta.received_at == received_at
    assert meta.received_at.tzinfo is UTC


def test_unit_contract_is_explicit_and_null_safe():
    assert normalize_ratio("5", unit="percent") == pytest.approx(0.05)
    assert normalize_ratio("0.05", unit="decimal") == pytest.approx(0.05)
    assert normalize_price("10.25") == pytest.approx(10.25)
    assert normalize_volume(12345, unit="shares") == 123
    assert normalize_volume(123.5, unit="lots") == pytest.approx(123.5)
    assert normalize_amount("12.5", unit="wan_yuan") == pytest.approx(125000)
    assert normalize_price("not-a-number") is None
    assert normalize_ratio(None) is None
    assert normalize_volume(None) is None
    with pytest.raises(ValueError, match="unit"):
        normalize_ratio(1, unit="basis_point")


def test_daily_and_instrument_normalizers_apply_canonical_symbol_and_date_contract():
    daily = normalize_daily(
        pl.DataFrame(
            {
                "ts_code": [" sh.600000 "],
                "trade_date": ["2026-09-04T09:30:00"],
                "open": [10],
                "high": [11],
                "low": [9],
                "close": [10.5],
                "vol": [100],
                "amt": [1000],
                "timestamp": [1788485400000],
            }
        )
    )
    assert daily["symbol"].to_list() == ["600000.SH"]
    assert daily["date"].to_list() == [date(2026, 9, 4)]
    assert daily["quote_ts"].to_list() == [1788485400000]
    assert daily.schema["close"] == pl.Float64

    factors = normalize_adj_factors(
        [{"symbol": "sh.600000", "trade_date": 20260904, "adj_factor": "1.05"}]
    )
    assert factors.to_dicts() == [
        {"symbol": "600000.SH", "trade_date": date(2026, 9, 4), "ex_factor": 1.05}
    ]

    instruments = normalize_instruments(
        [{"symbol": "sz.000001", "name": "平安银行", "exchange": "SZSE"}],
        asset_type="stock",
    )
    assert instruments.to_dicts() == [
        {
            "symbol": "000001.SZ",
            "name": "平安银行",
            "code": "000001",
            "exchange": "SZ",
            "asset_type": "stock",
            "source": "tickflow",
        }
    ]


def test_epoch_and_received_at_contracts_are_utc_and_millisecond_based():
    value = datetime(2026, 9, 4, 9, 30, tzinfo=timezone(timedelta(hours=8)))
    assert normalize_epoch_ms(value) == 1788485400000
    assert normalize_epoch_ms("1788485400000") == 1788485400000
    assert normalize_epoch_ms("bad") is None
    meta = CanonicalQuoteMeta(symbol="000001.SZ", received_at="2026-09-04T01:30:00+00:00")
    assert meta.received_at == datetime(2026, 9, 4, 1, 30, tzinfo=UTC)
