"""Provider health/retry/fallback governance contract tests."""
from __future__ import annotations

from app.data_providers.capabilities import build_capability_matrix
from app.data_providers.health import (
    ProviderHealthRegistry,
    RetryPolicy,
    call_with_retry,
)


def test_transient_error_retries_with_exponential_backoff():
    health = ProviderHealthRegistry()
    sleeps: list[float] = []
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("upstream timeout")
        return "ok"

    result = call_with_retry(
        "fuyao",
        "realtime",
        operation,
        policy=RetryPolicy(
            max_attempts=3,
            base_delay_seconds=0.1,
            max_delay_seconds=1.0,
        ),
        sleep=sleeps.append,
        health=health,
    )

    assert result == "ok"
    assert calls == 3
    assert sleeps == [0.1, 0.2]
    row = health.snapshot()[0]
    assert row["calls"] == 1
    assert row["successes"] == 1
    assert row["failures"] == 0
    assert row["retries"] == 2
    assert row["last_retry_delay_seconds"] == 0.2
    assert row["health"] == "healthy"


def test_auth_error_does_not_retry_and_is_redacted():
    health = ProviderHealthRegistry()
    calls = 0

    class UnauthorizedError(Exception):
        status_code = 401

    def operation():
        nonlocal calls
        calls += 1
        raise UnauthorizedError("api_key=secret-value")

    try:
        call_with_retry(
            "fuyao",
            "financial",
            operation,
            policy=RetryPolicy(max_attempts=4),
            sleep=lambda _delay: calls,
            health=health,
        )
    except UnauthorizedError:
        pass
    else:
        raise AssertionError("expected provider error")

    assert calls == 1
    row = health.snapshot()[0]
    assert row["failures"] == 1
    assert row["retries"] == 0
    assert row["last_error"] == "api_key=[REDACTED]"
    assert row["health"] == "degraded"


def test_three_consecutive_failures_make_provider_unavailable():
    health = ProviderHealthRegistry()
    for _ in range(3):
        health.record_failure("freestockdb", "daily", "connection refused")

    row = health.snapshot()[0]
    assert row["calls"] == 3
    assert row["error_rate"] == 1.0
    assert row["consecutive_failures"] == 3
    assert row["health"] == "unavailable"

    health.record_success("freestockdb", "daily", latency_ms=12)
    assert health.health_for("freestockdb", "daily") == "healthy"


def test_fallback_is_visible_without_exposing_provider_objects():
    health = ProviderHealthRegistry()
    health.record_fallback(
        "fuyao",
        "realtime",
        reason="provider_call_failed",
        error="token=secret-value",
    )

    row = health.snapshot()[0]
    assert row["fallbacks"] == 1
    assert row["health"] == "degraded"
    assert row["last_error"] == "token=[REDACTED]"


def test_capability_matrix_uses_runtime_health(monkeypatch):
    from app.data_providers import custom as custom_sources
    from app.data_providers.health import get_provider_health_registry

    registry = get_provider_health_registry()
    registry.clear()
    monkeypatch.setattr(
        custom_sources,
        "list_plugins",
        lambda: [{
            "name": "fuyao",
            "display_name": "fuyao",
            "datasets": ["realtime"],
            "available": True,
            "status": "ok",
        }],
    )
    monkeypatch.setattr(custom_sources, "list_sources", lambda: [])
    for _ in range(3):
        registry.record_failure("fuyao", "realtime", "upstream down")

    matrix = build_capability_matrix(
        {
            "daily_data_provider": "tickflow",
            "adj_factor_provider": "tickflow",
            "minute_data_provider": "tickflow",
            "full_minute_data_provider": "tickflow",
            "depth5_data_provider": "tickflow",
            "realtime_data_provider": "fuyao",
            "financial_data_provider": "tickflow",
        },
        tickflow_tier="expert",
    )
    realtime = next(
        item for item in matrix["capabilities"] if item["id"] == "realtime"
    )
    assert realtime["health"] == "unavailable"
    assert realtime["status"] == "DEGRADED"
    fuyao = next(
        candidate
        for candidate in realtime["candidates"]
        if candidate["name"] == "fuyao"
    )
    assert fuyao["status"] == "unavailable"
    registry.clear()


def test_provider_health_api_returns_filterable_serializable_snapshot():
    from app.api import settings as settings_api
    from app.data_providers.health import get_provider_health_registry

    registry = get_provider_health_registry()
    registry.clear()
    registry.record_success("tickflow", "daily", latency_ms=8)
    registry.record_failure("fuyao", "realtime", "api_key=secret")
    registry.record_fallback("fuyao", "realtime", reason="provider_call_failed")

    result = settings_api.get_provider_health(provider="fuyao", dataset="realtime")

    assert result["summary"] == {
        "providers": 1,
        "calls": 1,
        "failures": 1,
        "error_rate": 1.0,
    }
    assert result["providers"][0]["provider"] == "fuyao"
    assert result["providers"][0]["fallbacks"] == 1
    assert "secret" not in str(result)
    registry.clear()
