"""Capability router and fallback provenance contract tests."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.data_providers import custom as custom_sources
from app.data_providers.base import ProviderRoute
from app.services import kline_sync


def test_tickflow_route_is_primary_not_fallback():
    route = custom_sources.resolve_route("tickflow", "minute")

    assert route == ProviderRoute(
        dataset="minute",
        requested_provider="tickflow",
        effective_provider="tickflow",
    )
    assert route.provenance() == {
        "dataset": "minute",
        "requested_provider": "tickflow",
        "effective_provider": "tickflow",
        "fallback": False,
        "fallback_reason": None,
    }


def test_custom_route_contains_provider_and_provenance(monkeypatch):
    provider = object()
    monkeypatch.setattr(custom_sources, "provider_has_dataset", lambda name, dataset: True)
    monkeypatch.setattr(custom_sources, "get_provider", lambda name: provider)

    route = custom_sources.resolve_route("fuyao", "realtime")

    assert route.provider is provider
    assert route.effective_provider == "fuyao"
    assert route.fallback is False
    assert route.provenance()["requested_provider"] == "fuyao"


def test_missing_dataset_is_explicit_tickflow_fallback(monkeypatch):
    monkeypatch.setattr(custom_sources, "provider_has_dataset", lambda name, dataset: False)

    route = custom_sources.resolve_route("fuyao", "minute")

    assert route.provider is None
    assert route.effective_provider == "tickflow"
    assert route.fallback is True
    assert route.fallback_reason == "dataset_unavailable"
    assert route.error is None


def test_broken_registry_is_explicit_resolution_fallback(monkeypatch):
    monkeypatch.setattr(
        custom_sources,
        "provider_has_dataset",
        MagicMock(side_effect=RuntimeError("registry broken")),
    )

    route = custom_sources.resolve_route("fuyao", "minute")

    assert route.fallback_reason == "provider_resolution_failed"
    assert route.error == "registry broken"
    assert route.provenance()["fallback_reason"] == "provider_resolution_failed"


def test_minute_call_failure_rewrites_route_provenance(monkeypatch):
    provider = MagicMock()
    provider.get_minute.side_effect = RuntimeError("upstream down")
    monkeypatch.setattr(kline_sync.preferences, "get_minute_data_provider", lambda: "fuyao")
    monkeypatch.setattr(kline_sync, "_resolve_minute_provider", lambda name: (provider, False, None))
    monkeypatch.setattr(
        kline_sync,
        "_resolve_provider_route",
        lambda name, dataset: ProviderRoute(
            dataset=dataset,
            requested_provider=name,
            effective_provider=name,
            provider=provider,
        ),
    )

    evidence: dict = {}
    df, fallback = kline_sync._try_custom_minute(
        ["600519.SH"],
        datetime(2026, 1, 15, 9, 25),
        datetime(2026, 1, 15, 15, 5),
        asset_type="stock",
        provenance_out=evidence,
    )

    assert df is None
    assert fallback is True
    assert evidence == {
        "dataset": "minute",
        "requested_provider": "fuyao",
        "effective_provider": "tickflow",
        "fallback": True,
        "fallback_reason": "provider_call_failed",
    }


def test_daily_call_failure_records_fallback_provenance(monkeypatch):
    provider = MagicMock()
    provider.get_daily.side_effect = RuntimeError("daily unavailable")
    monkeypatch.setattr(kline_sync.preferences, "get_daily_data_provider", lambda: "fuyao")
    monkeypatch.setattr(
        kline_sync,
        "_resolve_provider_route",
        lambda name, dataset: ProviderRoute(
            dataset=dataset,
            requested_provider=name,
            effective_provider=name,
            provider=provider,
        ),
    )
    capset = SimpleNamespace(has=lambda _cap: False)
    evidence: dict = {}

    rows = kline_sync.sync_and_persist_daily_batch(
        ["600519.SH"],
        MagicMock(),
        capset,
        provenance_out=evidence,
    )

    assert rows == 0
    assert evidence["dataset"] == "daily"
    assert evidence["effective_provider"] == "tickflow"
    assert evidence["fallback_reason"] == "provider_call_failed"


def test_adj_factor_call_failure_records_fallback_provenance(monkeypatch):
    provider = MagicMock()
    provider.get_adj_factors.side_effect = RuntimeError("factor unavailable")
    monkeypatch.setattr(kline_sync.preferences, "get_adj_factor_provider", lambda: "fuyao")
    monkeypatch.setattr(
        kline_sync,
        "_resolve_provider_route",
        lambda name, dataset: ProviderRoute(
            dataset=dataset,
            requested_provider=name,
            effective_provider=name,
            provider=provider,
        ),
    )
    capset = SimpleNamespace(has=lambda _cap: False)
    evidence: dict = {}

    rows, affected = kline_sync.sync_adj_factor(
        ["600519.SH"],
        MagicMock(),
        capset,
        provenance_out=evidence,
    )

    assert rows == 0 and affected == []
    assert evidence["dataset"] == "adj_factor"
    assert evidence["effective_provider"] == "tickflow"
    assert evidence["fallback_reason"] == "provider_call_failed"
