"""Offline cross-provider golden tests for TASK-0204."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from app.data_providers import financial as financial_contract
from app.data_providers import tickflow_provider
from app.data_providers.custom.config import CustomSourceConfig, DatasetConfig
from app.data_providers.custom.provider import GenericHTTPProvider
from app.plugins.freestockdb import bridge
from app.plugins.freestockdb.provider import FreeStockDBProvider
from app.plugins.fuyao import provider as fuyao_module
from app.plugins.fuyao.client import FuyaoError
from app.plugins.fuyao.provider import FuyaoProvider
from app.services import financial_sync
from app.tickflow.capabilities import Cap, CapabilityLimits, CapabilitySet

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "provider_golden" / "market.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _assert_row(actual: dict, expected: dict, *, tolerances: dict[str, float] | None = None):
    tolerances = tolerances or {}
    for field, value in expected.items():
        assert field in actual, f"missing canonical field: {field}"
        if isinstance(value, float):
            assert actual[field] == pytest.approx(value, abs=tolerances.get(field, 1e-9))
        elif field in {"date", "trade_date"} and isinstance(value, str):
            assert actual[field] == date.fromisoformat(value)
        elif field == "datetime" and isinstance(value, str):
            assert actual[field].isoformat() == value
        else:
            assert actual[field] == value


def _free_client(monkeypatch, responses: dict[str, list[dict]]):
    class FakeClient:
        def fetch_flat(self, dataset, **kwargs):
            return [dict(row) for row in responses.get(dataset, [])]

        def close(self):
            pass

    monkeypatch.setattr(bridge, "FreeStockDBClient", lambda **kwargs: FakeClient())


def _tickflow_client(monkeypatch, fixture: dict):
    class FakeKlines:
        def batch(self, symbols, **kwargs):
            return fixture

        def ex_factors(self, symbols, **kwargs):
            return [fixture]

    monkeypatch.setattr(
        tickflow_provider,
        "get_client",
        lambda: SimpleNamespace(klines=FakeKlines()),
    )


def test_daily_golden_converges_tickflow_freestockdb_and_fuyao(monkeypatch):
    expected = FIXTURE["daily"]["expected"]
    start = datetime(2026, 9, 4)
    end = datetime(2026, 9, 4)

    _tickflow_client(monkeypatch, FIXTURE["daily"]["tickflow"])
    tickflow = tickflow_provider.TickFlowProvider().get_daily(
        [expected["symbol"]], start, end, "stock"
    ).to_dicts()[0]

    _free_client(monkeypatch, {"daily": [FIXTURE["daily"]["freestockdb"]]})
    freestockdb = FreeStockDBProvider().get_daily(
        [expected["symbol"]], start, end, "stock"
    ).to_dicts()[0]

    fuyao = FuyaoProvider()
    monkeypatch.setattr(
        fuyao,
        "_ensure_dump",
        lambda *args: (_ for _ in ()).throw(FuyaoError("offline golden fixture")),
    )
    monkeypatch.setattr(fuyao, "_daily_from_big_dump", lambda *args: None)
    monkeypatch.setattr(
        fuyao,
        "_historical_bars",
        lambda *args: [FIXTURE["daily"]["fuyao"]],
    )
    fuyao_row = fuyao.get_daily([expected["symbol"]], start, end, "stock").to_dicts()[0]

    for row in (tickflow, freestockdb, fuyao_row):
        _assert_row(row, expected)
    assert tickflow["volume"] == freestockdb["volume"] == fuyao_row["volume"] == 1000.0


def test_minute_golden_converges_freestockdb_and_custom_http(monkeypatch):
    expected = FIXTURE["minute"]["expected"]
    start = datetime(2026, 9, 4)
    end = datetime(2026, 9, 4)

    _free_client(monkeypatch, {"minute": [FIXTURE["minute"]["freestockdb"]]})
    free_row = FreeStockDBProvider().get_minute(
        [expected["symbol"]], start, end, "stock"
    ).to_dicts()[0]

    custom = GenericHTTPProvider(
        CustomSourceConfig(
            name="golden-custom",
            display_name="Golden Custom",
            datasets={
                "minute": DatasetConfig(
                    url="https://golden.invalid/minute",
                    field_map={
                        "code": "symbol",
                        "time": "datetime",
                        "open": "open",
                        "high": "high",
                        "low": "low",
                        "close": "close",
                        "volume": "volume",
                        "amount": "amount",
                    },
                )
            },
        )
    )
    monkeypatch.setattr(
        custom,
        "_request_rows",
        lambda cfg, **kwargs: [FIXTURE["minute"]["custom"]],
    )
    custom_row = custom.get_minute([expected["symbol"]], start, end).to_dicts()[0]

    for row in (free_row, custom_row):
        _assert_row(row, expected)
    assert free_row["volume"] == custom_row["volume"] == 12.0


def test_realtime_golden_converges_freestockdb_and_fuyao(monkeypatch):
    expected = FIXTURE["realtime"]["expected"]
    _free_client(monkeypatch, {"realtime": [FIXTURE["realtime"]["freestockdb"]]})
    free_row = FreeStockDBProvider().get_realtime()[0]

    class FakeFuyaoClient:
        def snapshot_all(self):
            return [FIXTURE["realtime"]["fuyao"]], FIXTURE["quote_timestamp_ms"]

        def close(self):
            pass

    monkeypatch.setattr(
        fuyao_module,
        "get_api_key",
        lambda: "golden-test-key",
    )
    fuyao = FuyaoProvider()
    fuyao._client = FakeFuyaoClient()
    fuyao_row = fuyao.get_realtime()[0]

    for row in (free_row, fuyao_row):
        _assert_row(
            row,
            expected,
            tolerances={"change_pct": 1e-12},
        )
    assert free_row["volume"] == fuyao_row["volume"] == 1200.0


def test_adjustment_factor_golden_converges_direct_and_fuyao_event_paths(monkeypatch):
    expected = FIXTURE["adj_factor"]["expected"]
    start = datetime(2026, 6, 29)
    end = datetime(2026, 6, 30)

    _tickflow_client(monkeypatch, FIXTURE["adj_factor"]["tickflow"])
    tickflow = tickflow_provider.TickFlowProvider().get_adj_factors(
        [expected["symbol"]], start, end, "stock"
    ).to_dicts()[0]

    _free_client(monkeypatch, {"adj_factor": [FIXTURE["adj_factor"]["freestockdb"]]})
    freestockdb = FreeStockDBProvider().get_adj_factors(
        [expected["symbol"]], start, end, "stock"
    ).to_dicts()[0]

    fuyao = FuyaoProvider()
    event = FIXTURE["adj_factor"]["fuyao_event"]
    event = {
        **event,
        "ex_date": date.fromisoformat(event["ex_date"]),
    }
    monkeypatch.setattr(
        fuyao,
        "_load_adj_events",
        lambda *args: pl.DataFrame([event]),
    )
    closes = {
        expected["symbol"]: {
            date.fromisoformat(day): value
            for day, value in FIXTURE["adj_factor"]["fuyao_reference_closes"].items()
        }
    }
    monkeypatch.setattr(fuyao, "_closes_from_dumps", lambda bounds: closes)
    fuyao_row = fuyao.get_adj_factors(
        [expected["symbol"]], start, end, "stock"
    ).to_dicts()[0]

    for row in (tickflow, freestockdb, fuyao_row):
        _assert_row(row, expected)
    assert fuyao_row["ex_factor"] == pytest.approx(100.0 / 80.0)


def test_financial_golden_retains_period_end_and_announce_date(monkeypatch):
    expected = FIXTURE["financial"]["expected"]

    class FakeFinancials:
        def metrics(self, symbols, latest=True):
            return {}

        def income(self, symbols, latest=True):
            return {expected["symbol"]: [FIXTURE["financial"]["tickflow"]]}

        def balance_sheet(self, symbols, latest=True):
            return {}

        def cash_flow(self, symbols, latest=True):
            return {}

        def shares(self, symbols, latest=True):
            return {}

    monkeypatch.setattr(
        "app.tickflow.client.get_client",
        lambda: SimpleNamespace(financials=FakeFinancials()),
    )
    monkeypatch.setattr(financial_sync, "_financial_is_custom", lambda: False)
    capset = CapabilitySet({
        Cap.FINANCIAL: CapabilityLimits(),
    })
    tickflow_row = financial_sync._fetch_table(
        "income", [expected["symbol"]], capset, latest_only=True
    ).to_dicts()[0]

    class FakeFuyaoClient:
        def financial_statements(self, stmt, symbol, limit=1):
            return [dict(FIXTURE["financial"]["fuyao"], thscode=symbol)]

    fuyao = FuyaoProvider()
    fuyao._client = FakeFuyaoClient()
    fuyao_row = fuyao.get_financials("income", [expected["symbol"]]).to_dicts()[0]

    for row in (tickflow_row, fuyao_row):
        _assert_row(row, expected)
    assert tickflow_row["period_end"] != tickflow_row["announce_date"]
    assert fuyao_row["period_end"] != fuyao_row["announce_date"]


def test_golden_fixture_is_small_and_network_free():
    assert FIXTURE_PATH.exists()
    assert FIXTURE_PATH.stat().st_size < 20_000
    assert financial_contract.canonical_columns("income")[:3] == (
        "symbol",
        "period_end",
        "announce_date",
    )
