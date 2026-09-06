"""ML-to-Unified-Signal adapter with no order or broker capability."""
from __future__ import annotations

from typing import Any

from app.services.transaction_store import TransactionStore
from app.strategy.unified_signal import adapt_signal


class MlSignalService:
    """Emit auditable ML observations/entries into the signal table only."""

    def __init__(self, store: TransactionStore) -> None:
        self.store = store

    def emit(
        self,
        *,
        model_version: str,
        symbol: str,
        as_of: str,
        action: str,
        kind: str = "observation",
        score: float | None = None,
        features: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        signal = adapt_signal(
            source="ml",  # type: ignore[arg-type]
            source_id=model_version,
            symbol=symbol,
            as_of=as_of,
            action=action,
            kind=kind,  # type: ignore[arg-type]
            score=score,
            payload={"features": dict(features or {}), **dict(payload or {})},
            provenance={"model_version": model_version, "research_only": True},
        )
        return self.store.create_signal({
            **signal.to_dict(),
            "idempotency_key": idempotency_key,
        })
