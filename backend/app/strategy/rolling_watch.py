"""Rolling watch state contract for polling-based monitor rules.

The monitor engine evaluates the same rule on every quote poll.  A cooldown
only limits time-based repeats; it does not know whether a condition has left
and re-entered.  This module keeps that distinction explicit and serializable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

ROLLING_WATCH_CONTRACT_VERSION = "1.0"
RollingWatchStatus = Literal["inactive", "active"]
RollingWatchTransition = Literal["inactive", "entered", "continued", "exited", "expired"]


@dataclass(frozen=True)
class RollingWatchState:
    """One rule/symbol/event state across quote polls."""

    contract_version: str
    rule_id: str
    symbol: str
    event_type: str
    status: RollingWatchStatus
    transition: RollingWatchTransition
    window_seconds: int
    first_seen_at: float | None
    last_seen_at: float | None
    last_matched_at: float | None
    last_triggered_at: float | None
    observation_count: int

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RollingWatchAdvance:
    """Result of advancing one state with the current poll observation."""

    state: RollingWatchState
    should_trigger: bool


def advance_rolling_watch(
    previous: RollingWatchState | None,
    *,
    rule_id: str,
    symbol: str,
    event_type: str,
    matched: bool,
    now: float,
    window_seconds: int,
    cooldown_seconds: int,
) -> RollingWatchAdvance:
    """Advance state and decide whether this poll creates a new alert.

    A present row that no longer matches exits immediately.  A row absent from
    a poll is not advanced by the engine; when it reappears, ``window_seconds``
    determines whether its previous active window has expired.  Cooldown is
    applied only to a new entry, so a continuously matching condition cannot
    replay after cooldown elapses.
    """
    window = max(0, int(window_seconds))
    cooldown = max(0, int(cooldown_seconds))
    expired = bool(
        previous
        and previous.is_active
        and previous.last_seen_at is not None
        and now - previous.last_seen_at > window
    )
    was_active = bool(previous and previous.is_active and not expired)
    previous_triggered = previous.last_triggered_at if previous else None

    if matched:
        entered = not was_active
        last_triggered = previous_triggered
        should_trigger = entered and (
            last_triggered is None or now - last_triggered >= cooldown
        )
        if should_trigger:
            last_triggered = now
        observation_count = (previous.observation_count + 1) if was_active and previous else 1
        state = RollingWatchState(
            contract_version=ROLLING_WATCH_CONTRACT_VERSION,
            rule_id=rule_id,
            symbol=symbol,
            event_type=event_type,
            status="active",
            transition="entered" if entered else "continued",
            window_seconds=window,
            first_seen_at=(previous.first_seen_at if was_active and previous else now),
            last_seen_at=now,
            last_matched_at=now,
            last_triggered_at=last_triggered,
            observation_count=observation_count,
        )
        return RollingWatchAdvance(state=state, should_trigger=should_trigger)

    state = RollingWatchState(
        contract_version=ROLLING_WATCH_CONTRACT_VERSION,
        rule_id=rule_id,
        symbol=symbol,
        event_type=event_type,
        status="inactive",
        transition="expired" if expired else "exited" if was_active else "inactive",
        window_seconds=window,
        first_seen_at=None,
        last_seen_at=now,
        last_matched_at=previous.last_matched_at if previous else None,
        last_triggered_at=previous_triggered,
        observation_count=0,
    )
    return RollingWatchAdvance(state=state, should_trigger=False)
