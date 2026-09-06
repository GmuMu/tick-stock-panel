"""Trading research workbench API.

The API exposes thesis, trade-plan, decision-gate and journal records only.
It deliberately has no order submission endpoint.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.services.transaction_store import (
    DECISION_STATUSES,
    JOURNAL_KINDS,
    TransactionConflictError,
    TransactionStore,
    TransactionValidationError,
)

router = APIRouter(prefix="/api/trading-research", tags=["trading-research"])


def _store(request: Request) -> TransactionStore:
    existing = getattr(request.app.state, "transaction_store", None)
    if existing is not None:
        return existing
    return TransactionStore(Path(request.app.state.repo.store.data_dir))


def _write_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TransactionConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, TransactionValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="交易研究记录保存失败")


class ThesisIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=160)
    direction: Literal["long", "short", "observe"] = "long"
    hypothesis: str = Field(min_length=1, max_length=10000)
    evidence: list[str] = Field(default_factory=list, max_length=30)
    counter_evidence: list[str] = Field(default_factory=list, max_length=30)
    status: Literal["open", "confirmed", "invalidated", "archived"] = "open"
    metadata: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=160)


class ThesisPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    direction: Literal["long", "short", "observe"] | None = None
    hypothesis: str | None = Field(default=None, min_length=1, max_length=10000)
    evidence: list[str] | None = Field(default=None, max_length=30)
    counter_evidence: list[str] | None = Field(default=None, max_length=30)
    status: Literal["open", "confirmed", "invalidated", "archived"] | None = None
    metadata: dict[str, object] | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, max_length=160)


class PlanIn(BaseModel):
    thesis_id: str | None = None
    symbol: str = Field(min_length=1, max_length=32)
    direction: Literal["buy", "sell", "observe"] = "buy"
    entry_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    target_price: float | None = Field(default=None, gt=0)
    position_pct: float | None = Field(default=None, ge=0, le=100)
    quantity: float | None = Field(default=None, ge=0)
    valid_from: str | None = None
    valid_until: str | None = None
    candidate_source: dict[str, object] = Field(default_factory=dict)
    status: Literal["draft", "active", "closed", "cancelled", "expired"] = "draft"
    notes: str = Field(default="", max_length=10000)
    idempotency_key: str | None = Field(default=None, max_length=160)


class PlanPatch(BaseModel):
    thesis_id: str | None = None
    entry_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    target_price: float | None = Field(default=None, gt=0)
    position_pct: float | None = Field(default=None, ge=0, le=100)
    quantity: float | None = Field(default=None, ge=0)
    valid_from: str | None = None
    valid_until: str | None = None
    candidate_source: dict[str, object] | None = None
    status: Literal["draft", "active", "closed", "cancelled", "expired"] | None = None
    notes: str | None = Field(default=None, max_length=10000)
    expected_revision: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, max_length=160)


class DecisionIn(BaseModel):
    plan_id: str
    status: Literal["pending", "approved", "rejected", "expired"] = "pending"
    rationale: str = Field(default="", max_length=10000)
    expires_at: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=160)


class DecisionTransition(BaseModel):
    status: Literal["pending", "approved", "rejected", "expired"]
    rationale: str = Field(default="", max_length=10000)
    expires_at: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, max_length=160)


class JournalIn(BaseModel):
    plan_id: str | None = None
    decision_id: str | None = None
    kind: Literal["plan", "decision", "order", "fill", "review", "note"]
    content: str = Field(min_length=1, max_length=20000)
    payload: dict[str, object] = Field(default_factory=dict)
    occurred_at: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=160)


@router.get("/summary")
def summary(request: Request):
    return _store(request).summary()


@router.get("/theses")
def list_theses(request: Request, limit: int = Query(100, ge=1, le=500)):
    return {"items": _store(request).list_theses(limit)}


@router.post("/theses")
def create_thesis(req: ThesisIn, request: Request):
    try:
        return {"item": _store(request).create_thesis(req.model_dump())}
    except Exception as exc:
        raise _write_error(exc) from exc


@router.patch("/theses/{thesis_id}")
def update_thesis(thesis_id: str, req: ThesisPatch, request: Request):
    try:
        return {"item": _store(request).update_thesis(thesis_id, req.model_dump(exclude_none=True))}
    except Exception as exc:
        raise _write_error(exc) from exc


@router.get("/plans")
def list_plans(request: Request, limit: int = Query(100, ge=1, le=500)):
    return {"items": _store(request).list_plans(limit)}


@router.post("/plans")
def create_plan(req: PlanIn, request: Request):
    try:
        return {"item": _store(request).create_plan(req.model_dump())}
    except Exception as exc:
        raise _write_error(exc) from exc


@router.patch("/plans/{plan_id}")
def update_plan(plan_id: str, req: PlanPatch, request: Request):
    try:
        return {"item": _store(request).update_plan(plan_id, req.model_dump(exclude_none=True))}
    except Exception as exc:
        raise _write_error(exc) from exc


@router.get("/decisions")
def list_decisions(request: Request, limit: int = Query(100, ge=1, le=500)):
    return {"items": _store(request).list_decisions(limit)}


@router.post("/decisions")
def create_decision(req: DecisionIn, request: Request):
    try:
        return {"item": _store(request).create_decision(req.model_dump())}
    except Exception as exc:
        raise _write_error(exc) from exc


@router.post("/decisions/{decision_id}/transition")
def transition_decision(decision_id: str, req: DecisionTransition, request: Request):
    if req.status not in DECISION_STATUSES:
        raise HTTPException(status_code=400, detail="无效的决策状态")
    try:
        return {"item": _store(request).transition_decision(decision_id, req.model_dump(exclude_none=True))}
    except Exception as exc:
        raise _write_error(exc) from exc


@router.get("/journal")
def list_journal(request: Request, limit: int = Query(200, ge=1, le=1000)):
    return {"items": _store(request).list_journal(limit)}


@router.post("/journal")
def create_journal(req: JournalIn, request: Request):
    if req.kind not in JOURNAL_KINDS:
        raise HTTPException(status_code=400, detail="无效的日志类型")
    try:
        return {"item": _store(request).create_journal(req.model_dump())}
    except Exception as exc:
        raise _write_error(exc) from exc


@router.get("/audit")
def list_audit(request: Request, limit: int = Query(200, ge=1, le=1000)):
    return {"items": _store(request).list_audit(limit)}
