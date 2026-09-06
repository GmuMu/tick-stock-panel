"""Research adapter API; it never creates orders or changes broker state."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.research.contract import ResearchArtifact
from app.research.ml_signal import MlSignalService
from app.research.quantmind import QuantMindAdapter
from app.services.transaction_store import TransactionStore

router = APIRouter(prefix="/api/research", tags=["research"])


def _data_dir(request: Request) -> Path:
    return Path(request.app.state.repo.store.data_dir)


def _quantmind(request: Request) -> QuantMindAdapter:
    return QuantMindAdapter(_data_dir(request))


def _store(request: Request) -> TransactionStore:
    existing = getattr(request.app.state, "transaction_store", None)
    return existing or TransactionStore(_data_dir(request))


class ResearchIn(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=160)
    symbol: str = Field(min_length=1, max_length=32)
    as_of: str = Field(min_length=1, max_length=40)
    thesis: str = Field(min_length=1, max_length=10000)
    score: float | None = None
    features: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class MlSignalIn(BaseModel):
    model_version: str = Field(min_length=1, max_length=160)
    symbol: str = Field(min_length=1, max_length=32)
    as_of: str = Field(min_length=1, max_length=40)
    action: str = Field(min_length=1, max_length=80)
    kind: Literal["entry", "exit", "observation"] = "observation"
    score: float | None = None
    features: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=160)


@router.get("/adapters")
def adapters() -> dict[str, Any]:
    return {
        "items": [{
            "name": "quantmind",
            "mode": "local_file_handoff",
            "network_enabled": False,
            "trading_enabled": False,
            "contract_version": "1.0",
        }],
    }


@router.get("/quantmind")
def list_quantmind(request: Request, limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    try:
        return {"items": [item.to_dict() for item in _quantmind(request).list_artifacts(limit)]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/quantmind")
def ingest_quantmind(body: ResearchIn, request: Request) -> dict[str, Any]:
    try:
        artifact = ResearchArtifact.from_dict({
            **body.model_dump(),
            "provider": "quantmind",
            "provenance": {**body.provenance, "adapter": "local_file_handoff"},
        })
        return {"item": _quantmind(request).ingest(artifact).to_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ml/signals")
def emit_ml_signal(body: MlSignalIn, request: Request) -> dict[str, Any]:
    try:
        item = MlSignalService(_store(request)).emit(**body.model_dump())
        return {"item": item, "orders_created": 0, "broker_calls": 0}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
