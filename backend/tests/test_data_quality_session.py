"""DataQuality and MarketSession contract tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.data_quality import DataQuality
from app.market_time import CN_TZ, market_session


def test_market_session_reports_continuous_morning_in_beijing_time():
    session = market_session(datetime(2026, 9, 4, 10, 0, tzinfo=CN_TZ))

    assert session.phase == "morning"
    assert session.trading_day is True
    assert session.is_continuous is True
    assert session.is_polling_window is True
    assert session.can_poll is True
    assert session.elapsed_minutes == 30


def test_market_session_handles_lunch_and_pre_afternoon_boundaries():
    lunch = market_session(datetime(2026, 9, 4, 11, 45, tzinfo=CN_TZ))
    pre_afternoon = market_session(datetime(2026, 9, 4, 12, 57, tzinfo=CN_TZ))

    assert lunch.to_dict()["phase"] == "morning_final"
    assert lunch.is_continuous is False
    assert lunch.elapsed_minutes == 120
    assert pre_afternoon.phase == "pre_afternoon"
    assert pre_afternoon.is_polling_window is True


def test_market_session_converts_aware_utc_and_rejects_holidays():
    utc_10 = datetime(2026, 9, 4, 2, 0, tzinfo=UTC)
    session = market_session(utc_10)
    holiday = market_session(
        datetime(2026, 9, 4, 10, 0, tzinfo=CN_TZ),
        trading_day=False,
    )

    assert session.session_date.isoformat() == "2026-09-04"
    assert session.phase == "morning"
    assert holiday.phase == "closed"
    assert holiday.can_poll is False
    assert holiday.reason == "holiday"


def test_market_session_weekend_is_closed():
    session = market_session(datetime(2026, 9, 5, 10, 0))

    assert session.to_dict() == {
        "date": "2026-09-05",
        "phase": "closed",
        "trading_day": False,
        "is_continuous": False,
        "is_polling_window": False,
        "can_poll": False,
        "elapsed_minutes": 0.0,
        "reason": "weekend",
    }


def test_data_quality_is_fail_closed_for_missing_partial_and_stale():
    now = datetime(2026, 9, 4, 10, 0, tzinfo=CN_TZ)
    complete = DataQuality.from_counts(
        "daily",
        expected_rows=100,
        actual_rows=100,
        observed_at=now,
        now=now,
        stale_after_seconds=60,
    )
    partial = DataQuality.from_counts(
        "daily",
        expected_rows=100,
        actual_rows=90,
        observed_at=now,
        now=now,
        stale_after_seconds=60,
    )
    missing = DataQuality.from_counts("daily", expected_rows=100, actual_rows=0)
    stale = DataQuality.from_observation(
        "realtime",
        observed_at=now - timedelta(seconds=61),
        now=now,
        stale_after_seconds=60,
    )

    assert complete.status == "FRESH"
    assert complete.usable is True
    assert partial.status == "PARTIAL"
    assert partial.usable is False
    assert missing.to_dict()["fail_closed"] is True
    assert stale.status == "STALE"
    assert stale.reason == "observation_stale"


def test_data_quality_invalid_input_is_not_usable_and_serializes():
    quality = DataQuality.from_counts(
        "minute",
        expected_rows=-1,
        actual_rows=10,
    )

    assert quality.status == "INVALID"
    assert quality.usable is False
    assert quality.to_dict()["fail_closed"] is True
    assert quality.to_dict()["reason"] == "invalid_counts"
