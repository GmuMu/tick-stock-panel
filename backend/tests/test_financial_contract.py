"""Canonical financial schema and point-in-time metadata tests."""
from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from app.data_providers.financial import canonical_columns, normalize_financial
from app.services import financial_sync, preferences
from app.tickflow.capabilities import CapabilitySet


def test_financial_contract_normalizes_aliases_dates_numbers_and_source():
    result = normalize_financial(
        [{
            "ts_code": "600519.SH",
            "report_period": datetime(2026, 6, 30, tzinfo=UTC),
            "report_date": "2026-08-15",
            "operating_income": "90703260964.48",
            "net_profit": "46033330566.78",
            "return_on_equity": "16.75",
            "vendor_note": "kept separately",
        }],
        "income",
        source="fixture",
    )

    assert result.columns[:4] == ["symbol", "period_end", "announce_date", "revenue"]
    row = result.to_dicts()[0]
    assert row["symbol"] == "600519.SH"
    assert row["period_end"] == "2026-06-30"
    assert row["announce_date"] == "2026-08-15"
    assert row["revenue"] == pytest.approx(90703260964.48)
    assert row["net_income"] == pytest.approx(46033330566.78)
    assert row["source"] == "fixture"
    assert row["vendor_note"] == "kept separately"
    assert "operating_income" not in result.columns
    assert "net_profit" not in result.columns


def test_financial_contract_uses_single_symbol_default_and_drops_invalid_identity():
    result = normalize_financial(
        [
            {"period_end": "2026-06-30", "total_shares": "1000000"},
            {"symbol": "bad", "period_end": "not-a-date", "total_shares": 2},
        ],
        "shares",
        symbols=["000001.SZ"],
    )

    assert result.height == 1
    assert result["symbol"].to_list() == ["000001.SZ"]
    assert result["total_shares"].to_list() == [1_000_000.0]


def test_financial_contract_does_not_guess_unknown_ratio_units():
    result = normalize_financial(
        [{
            "symbol": "600519.SH",
            "period_end": "2026-06-30",
            "announce_date": "2026-08-15",
            "roe": "16.75",
            "gross_margin": "89.5",
        }],
        "metrics",
        source="fixture",
    )

    assert result.schema["roe"] == pl.Float64
    assert result["roe"][0] == pytest.approx(16.75)
    assert result["gross_margin"][0] == pytest.approx(89.5)


def test_financial_contract_exposes_stable_columns_by_table():
    assert canonical_columns("metrics")[:3] == ("symbol", "period_end", "announce_date")
    assert "net_income_attributable" in canonical_columns("income")
    assert "total_liabilities" in canonical_columns("balance_sheet")
    assert "net_operating_cash_flow" in canonical_columns("cash_flow")
    assert "float_shares" in canonical_columns("shares")


def test_custom_financial_provider_is_normalized_at_sync_boundary(monkeypatch):
    class Provider:
        name = "custom-financial"

        def get_financials(self, table, symbols, latest_only=True):
            assert table == "income"
            assert symbols == ["600519.SH"]
            assert latest_only is True
            return pl.DataFrame([{
                "ts_code": "600519.SH",
                "report_period": "2026-06-30",
                "report_date": "2026-08-15",
                "operating_income": "1000",
                "net_profit": "100",
            }])

    from app.data_providers import custom as custom_sources

    monkeypatch.setattr(financial_sync, "_financial_is_custom", lambda: True)
    monkeypatch.setattr(preferences, "get_financial_provider", lambda: "custom-financial")
    monkeypatch.setattr(custom_sources, "get_provider", lambda _name: Provider())

    result = financial_sync._fetch_table(
        "income", ["600519.SH"], CapabilitySet(), latest_only=True
    )

    assert result.to_dicts()[0] == {
        "symbol": "600519.SH",
        "period_end": "2026-06-30",
        "announce_date": "2026-08-15",
        "revenue": 1000.0,
        "operating_cost": None,
        "operating_profit": None,
        "selling_expense": None,
        "admin_expense": None,
        "rd_expense": None,
        "financial_expense": None,
        "non_operating_income": None,
        "non_operating_expense": None,
        "total_profit": None,
        "income_tax": None,
        "net_income": 100.0,
        "net_income_attributable": None,
        "net_income_deducted": None,
        "basic_eps": None,
        "diluted_eps": None,
        "source": "custom-financial",
    }
