"""Offline contract tests for the free-stockdb Bridge / Provider."""
from __future__ import annotations

from datetime import datetime

import httpx
import polars as pl

from app.plugins.freestockdb import bridge
from app.plugins.freestockdb.provider import FreeStockDBProvider


def _client(monkeypatch, payloads):
    calls = []
    client_cls = bridge.FreeStockDBClient

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        for suffix, payload in payloads.items():
            if path.endswith(suffix):
                return httpx.Response(200, json=payload, request=request)
        return httpx.Response(404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        bridge,
        "FreeStockDBClient",
        lambda *args, **kwargs: client_cls(
            base_url="http://free-stockdb.test",
            http=client,
        ),
    )
    return calls


def test_bridge_unwraps_envelope_and_preserves_symbol_keys(monkeypatch):
    calls = _client(monkeypatch, {
        "/api/v1/stocks/daily": {
            "data": {
                "600519.SH": [
                    {"date": "2026-09-04", "open": 1400, "high": 1410, "low": 1390,
                     "close": 1405, "volume": 100000, "amount": 123456789},
                ],
            },
        },
    })
    df = FreeStockDBProvider().get_daily(
        ["600519.SH"], datetime(2026, 9, 1), datetime(2026, 9, 5)
    )
    assert df.height == 1
    assert df["symbol"].to_list() == ["600519.SH"]
    assert df["date"].to_list() == [datetime(2026, 9, 4).date()]
    assert df["volume"].to_list() == [1000.0]
    assert calls[0].url.path.endswith("/api/v1/stocks/daily")
    assert calls[0].url.params["symbols"] == "600519.SH"
    assert calls[0].url.params["start"] == "2026-09-01"


def test_provider_normalizes_minute_and_realtime_units(monkeypatch):
    _client(monkeypatch, {
        "/api/v1/stocks/minute": {
            "rows": [{
                "ts_code": "600519.SH",
                "datetime": "2026-09-04T09:35:00+08:00",
                "open": 1400,
                "high": 1402,
                "low": 1399,
                "close": 1401,
                "vol": 1200,
                "amount": 1681200,
            }],
        },
        "/api/v1/stocks/tick": {
            "items": [{
                "code": "600519",
                "exchange": "SH",
                "name": "贵州茅台",
                "price": 1401,
                "prev_close": 1400,
                "vol": 120000,
                "amount": 168120000,
                "change_percent": 0.0714,
                "timestamp": 1788485700000,
            }],
        },
    })
    provider = FreeStockDBProvider()
    minute = provider.get_minute(
        ["600519.SH"], datetime(2026, 9, 4), datetime(2026, 9, 4), freq="1m"
    )
    realtime = provider.get_realtime()
    assert minute.schema["datetime"] == pl.Datetime("us")
    assert minute["datetime"][0].hour == 9
    assert minute["volume"].to_list() == [12.0]
    assert realtime[0]["symbol"] == "600519.SH"
    assert realtime[0]["volume"] == 1200.0
    assert realtime[0]["change_pct"] == 0.000714


def test_provider_normalizes_adj_factors_and_instruments(monkeypatch):
    _client(monkeypatch, {
        "/api/v1/stocks/adj-factors": {
            "result": [{
                "ts_code": "600519.SH",
                "trade_date": "2026-09-04",
                "adj_factor": 1.25,
            }],
        },
        "/api/v1/stocks/instruments": {
            "data": [{"code": "600519", "exchange": "SH", "name": "贵州茅台"}],
        },
    })
    provider = FreeStockDBProvider()
    factors = provider.get_adj_factors(["600519.SH"], None, None)
    instruments = provider.get_instruments()
    assert factors["ex_factor"].to_list() == [1.25]
    assert instruments["symbol"].to_list() == ["600519.SH"]
    assert instruments["source"].to_list() == ["freestockdb"]


def test_bridge_tries_fallback_path_on_404(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/api/stocks/tick":
            return httpx.Response(200, json={"data": []}, request=request)
        return httpx.Response(404, request=request)

    result = bridge.FreeStockDBClient(
        base_url="http://free-stockdb.test",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    ).fetch_flat("realtime")
    assert result == []
    assert [request.url.path for request in calls] == [
        "/api/v1/stocks/tick",
        "/api/stocks/tick",
    ]


def test_plugin_is_discoverable_and_declares_four_datasets():
    from app.data_providers import custom as custom_sources

    plugin = next(item for item in custom_sources.list_plugins() if item["name"] == "freestockdb")
    assert plugin["datasets"] == ["daily", "minute", "realtime", "adj_factor"]
    assert plugin["runtime"] == "none"
