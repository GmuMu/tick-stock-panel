"""Versioned signal boundary for strategy, indicator and monitor producers.

The adapters preserve the producer payload and semantics.  They only add a
stable identity, source classification and provenance so later paper trading
can consume different signal types through one auditable contract.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SIGNAL_CONTRACT_VERSION = "1.0"
SignalSource = Literal["strategy", "indicator", "custom", "monitor", "manual", "ml"]
SignalKind = Literal["entry", "exit", "observation"]


@dataclass(frozen=True)
class UnifiedSignal:
    signal_id: str
    symbol: str
    as_of: str
    source: SignalSource
    source_id: str
    kind: SignalKind
    action: str
    score: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    contract_version: str = SIGNAL_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def signal_id(source: str, source_id: str, symbol: str, as_of: str, action: str) -> str:
    raw = "|".join((source, source_id, symbol, as_of, action)).encode()
    return f"sig_{hashlib.sha256(raw).hexdigest()[:24]}"


def adapt_signal(
    *,
    source: SignalSource,
    source_id: str,
    symbol: str,
    as_of: str,
    action: str,
    kind: SignalKind = "observation",
    score: float | None = None,
    payload: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> UnifiedSignal:
    if not symbol.strip() or not source_id.strip() or not as_of.strip() or not action.strip():
        raise ValueError("Signal 必须包含 symbol、as_of、source_id 和 action")
    if score is not None and (score != score or score in (float("inf"), float("-inf"))):
        raise ValueError("Signal score 必须是有限数值")
    return UnifiedSignal(
        signal_id=signal_id(source, source_id, symbol, as_of, action),
        symbol=symbol.strip().upper(),
        as_of=as_of.strip(),
        source=source,
        source_id=source_id.strip(),
        kind=kind,
        action=action.strip(),
        score=score,
        payload=dict(payload or {}),
        provenance={"contract_version": SIGNAL_CONTRACT_VERSION, **dict(provenance or {})},
    )


def from_strategy_candidate(candidate: dict[str, Any]) -> UnifiedSignal:
    return adapt_signal(
        source="strategy",
        source_id=str(candidate.get("strategy_id") or "unknown"),
        symbol=str(candidate["symbol"]),
        as_of=str(candidate["as_of"]),
        action="entry",
        kind="entry",
        score=float(candidate["score"]) if candidate.get("score") is not None else None,
        payload=candidate,
        provenance=dict(candidate.get("provenance") or {}),
    )


def from_monitor_event(event: dict[str, Any]) -> UnifiedSignal:
    source_id = str(event.get("rule_id") or event.get("strategy_id") or "monitor")
    action = str(event.get("action") or event.get("event") or "observe")
    return adapt_signal(
        source="monitor",
        source_id=source_id,
        symbol=str(event["symbol"]),
        as_of=str(event.get("as_of") or event.get("timestamp") or "unknown"),
        action=action,
        kind="exit" if action.lower() in {"exit", "sell", "stop"} else "entry" if action.lower() in {"entry", "buy"} else "observation",
        payload=event,
        provenance={"event_source": event.get("source", "monitor")},
    )


def from_custom_signal(signal: dict[str, Any], *, symbol: str, as_of: str) -> UnifiedSignal:
    return adapt_signal(
        source="custom",
        source_id=str(signal.get("id") or signal.get("name") or "custom"),
        symbol=symbol,
        as_of=as_of,
        action=str(signal.get("kind") or "observe"),
        kind="entry" if signal.get("kind") == "entry" else "exit" if signal.get("kind") == "exit" else "observation",
        payload=signal,
        provenance={"source_contract": "custom_signal"},
    )


def from_indicator_event(event: dict[str, Any]) -> UnifiedSignal:
    return adapt_signal(
        source="indicator",
        source_id=str(event.get("indicator") or event.get("name") or "indicator"),
        symbol=str(event["symbol"]),
        as_of=str(event["as_of"]),
        action=str(event.get("action") or "observe"),
        kind=str(event.get("kind") or "observation"),
        score=float(event["score"]) if event.get("score") is not None else None,
        payload=event,
        provenance={"source_contract": "indicator_event"},
    )


def jsonable(signal: UnifiedSignal) -> dict[str, Any]:
    payload = signal.to_dict()
    json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return payload
