"""Versioned multi-signal resonance state for monitor rules.

Resonance is intentionally a pure state transition helper.  The existing
MonitorRuleEngine owns evaluation, cooldown and delivery; this module only
defines how independent signal observations accumulate within a time window.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

RESONANCE_CONTRACT_VERSION = "1.0"
ResonanceStatus = Literal["inactive", "pending", "active"]
ResonanceTransition = Literal["inactive", "pending", "entered", "continued", "exited", "expired"]


@dataclass(frozen=True)
class ResonanceState:
    contract_version: str
    rule_id: str
    symbol: str
    status: ResonanceStatus
    transition: ResonanceTransition
    window_seconds: int
    min_signals: int
    active_signals: tuple[str, ...]
    signal_times: dict[str, float]
    first_signal_at: float | None
    last_signal_at: float | None
    last_triggered_at: float | None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["active_signals"] = list(self.active_signals)
        return result


@dataclass(frozen=True)
class ResonanceAdvance:
    state: ResonanceState
    should_trigger: bool


def advance_resonance(
    previous: ResonanceState | None,
    *,
    rule_id: str,
    symbol: str,
    observed_signals: set[str],
    now: float,
    window_seconds: int,
    min_signals: int,
    cooldown_seconds: int,
) -> ResonanceAdvance:
    """Accumulate signal timestamps and emit only on inactive -> active edges."""
    window = max(1, int(window_seconds))
    minimum = max(2, int(min_signals))
    cooldown = max(0, int(cooldown_seconds))

    timestamps: dict[str, float] = {}
    if previous is not None:
        for signal, timestamp in previous.signal_times.items():
            if now - timestamp <= window:
                timestamps[signal] = timestamp
    for signal in observed_signals:
        timestamps[signal] = now

    active = tuple(sorted(timestamps))
    count = len(active)
    previous_active = previous is not None and previous.status == "active"
    current_active = count >= minimum
    last_triggered = previous.last_triggered_at if previous else None
    should_trigger = current_active and not previous_active and (
        last_triggered is None or now - last_triggered >= cooldown
    )
    if should_trigger:
        last_triggered = now

    if current_active:
        status: ResonanceStatus = "active"
        transition: ResonanceTransition = "entered" if not previous_active else "continued"
    elif count:
        status = "pending"
        transition = "pending"
    else:
        status = "inactive"
        transition = "expired" if previous and previous.status in {"pending", "active"} else "inactive"

    state = ResonanceState(
        contract_version=RESONANCE_CONTRACT_VERSION,
        rule_id=rule_id,
        symbol=symbol,
        status=status,
        transition=transition,
        window_seconds=window,
        min_signals=minimum,
        active_signals=active,
        signal_times=timestamps,
        first_signal_at=(
            previous.first_signal_at
            if previous is not None and count and previous.status in {"pending", "active"}
            else now if count else None
        ),
        last_signal_at=now if observed_signals else previous.last_signal_at if previous else None,
        last_triggered_at=last_triggered,
    )
    return ResonanceAdvance(state=state, should_trigger=should_trigger)
