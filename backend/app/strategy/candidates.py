"""Stable strategy candidate model built from the existing StrategyResult."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

CANDIDATE_MODEL_VERSION = "1.0"


@dataclass(frozen=True)
class StrategyCandidate:
    """One strategy selection with enough provenance for later review/backtest."""

    candidate_id: str
    symbol: str
    as_of: str
    strategy_id: str
    rank: int
    score: float | None
    row: dict[str, Any] = field(default_factory=dict)
    signals: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["signals"] = list(self.signals)
        return value


@dataclass(frozen=True)
class StrategyCandidateBatch:
    """Immutable candidate snapshot for one strategy/date execution."""

    model_version: str
    strategy_id: str
    as_of: str
    candidates: tuple[StrategyCandidate, ...]
    provenance: dict[str, Any] = field(default_factory=dict)
    data_quality: dict[str, Any] = field(default_factory=dict)
    seed_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "strategy_id": self.strategy_id,
            "as_of": self.as_of,
            "seed_id": self.seed_id,
            "candidates": [item.to_dict() for item in self.candidates],
            "provenance": dict(self.provenance),
            "data_quality": dict(self.data_quality),
        }


def candidate_id(strategy_id: str, as_of: str, symbol: str) -> str:
    """Return a deterministic id for idempotent EOD seed writes."""
    raw = f"{strategy_id}|{as_of}|{symbol}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def seed_id(strategy_id: str, as_of: str, strategy_version: str) -> str:
    raw = f"{strategy_id}|{as_of}|{strategy_version}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def batch_from_result(result: Any) -> StrategyCandidateBatch:
    """Convert a StrategyResult without changing its existing API semantics."""
    rows_by_symbol = {
        str(row.get("symbol")): dict(row)
        for row in (getattr(result, "rows", None) or [])
        if row.get("symbol")
    }
    scores = getattr(result, "scores", None) or {}
    symbols = list(scores)
    for symbol in rows_by_symbol:
        if symbol not in symbols:
            symbols.append(symbol)
    symbols.sort(key=lambda symbol: (scores.get(symbol) is None, -(scores.get(symbol) or 0.0), symbol))
    signal_map = {
        str(item.get("symbol")): tuple(item.get("signals") or ())
        for item in (getattr(result, "entry_signal_hits", None) or [])
    }
    strategy_id = str(result.strategy_id)
    as_of = str(result.as_of)
    provenance = dict(getattr(result, "provenance", None) or {})
    version = str(getattr(result, "strategy_version", "1.0.0"))
    candidates = tuple(
        StrategyCandidate(
            candidate_id=candidate_id(strategy_id, as_of, symbol),
            symbol=symbol,
            as_of=as_of,
            strategy_id=strategy_id,
            rank=index,
            score=float(scores[symbol]) if symbol in scores else None,
            row=rows_by_symbol.get(symbol, {}),
            signals=signal_map.get(symbol, ()),
            provenance=provenance,
        )
        for index, symbol in enumerate(symbols, start=1)
    )
    return StrategyCandidateBatch(
        model_version=CANDIDATE_MODEL_VERSION,
        strategy_id=strategy_id,
        as_of=as_of,
        candidates=candidates,
        provenance=provenance,
        seed_id=seed_id(strategy_id, as_of, version),
    )


def jsonable_batch(batch: StrategyCandidateBatch) -> dict[str, Any]:
    """Validate that the public candidate payload remains JSON-compatible."""
    payload = batch.to_dict()
    json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return payload
