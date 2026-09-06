"""Paper trading API for the Phase 9/10 local simulation boundary."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.services.transaction_store import (
    OUTBOX_STATUSES,
    TransactionConflictError,
    TransactionStore,
    TransactionValidationError,
)
from app.strategy.unified_signal import adapt_signal

router = APIRouter(prefix="/api/paper-trading", tags=["paper-trading"])


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
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="纸面交易记录保存失败")


class SignalIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    as_of: str = Field(min_length=1, max_length=40)
    source: Literal["strategy", "indicator", "custom", "monitor", "manual", "ml"]
    source_id: str = Field(min_length=1, max_length=160)
    kind: Literal["entry", "exit", "observation"] = "observation"
    action: str = Field(min_length=1, max_length=80)
    score: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=160)


class SignalAdaptIn(BaseModel):
    source: Literal["strategy", "indicator", "custom", "monitor", "manual", "ml"]
    source_id: str = Field(min_length=1, max_length=160)
    symbol: str = Field(min_length=1, max_length=32)
    as_of: str = Field(min_length=1, max_length=40)
    action: str = Field(min_length=1, max_length=80)
    kind: Literal["entry", "exit", "observation"] = "observation"
    score: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=160)


class RiskIn(BaseModel):
    plan_id: str
    snapshot: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=160)


class OrderIn(BaseModel):
    plan_id: str
    signal_id: str | None = None
    client_order_id: str | None = Field(default=None, max_length=160)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=160)


class FillIn(BaseModel):
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    trade_date: str | None = None
    occurred_at: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=160)


class OrderTransitionIn(BaseModel):
    status: Literal["new", "accepted", "partially_filled", "filled", "cancelled", "rejected"]
    reason: str | None = Field(default=None, max_length=1000)
    expected_revision: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, max_length=160)


class OutboxIn(BaseModel):
    status: Literal["pending", "sent", "failed"]
    error: str | None = Field(default=None, max_length=1000)


class ReviewIn(BaseModel):
    as_of: str = Field(min_length=10, max_length=40)
    summary: str = Field(default="", max_length=10000)
    idempotency_key: str | None = Field(default=None, max_length=160)


@router.get("/summary")
def paper_summary(request: Request):
    return _store(request).paper_summary()


@router.get("/signals")
def list_signals(request: Request, limit: int = Query(200, ge=1, le=1000)):
    return {"items": _store(request).list_signals(limit)}


@router.post("/signals")
def create_signal(req: SignalIn, request: Request):
    try:
        signal = adapt_signal(**req.model_dump(exclude={"idempotency_key"}))
        return {"item": _store(request).create_signal({**signal.to_dict(), "idempotency_key": req.idempotency_key})}
    except Exception as exc:
        raise _write_error(exc) from exc


@router.post("/signals/adapt")
def adapt_and_create_signal(req: SignalAdaptIn, request: Request):
    try:
        signal = adapt_signal(**req.model_dump(exclude={"idempotency_key"}))
        return {"item": _store(request).create_signal({**signal.to_dict(), "idempotency_key": req.idempotency_key})}
    except Exception as exc:
        raise _write_error(exc) from exc


@router.post("/risk/check")
def evaluate_risk(req: RiskIn, request: Request):
    try:
        return _store(request).evaluate_risk(req.plan_id, req.snapshot, idempotency_key=req.idempotency_key)
    except Exception as exc:
        raise _write_error(exc) from exc


@router.get("/risk/checks")
def list_risk_checks(request: Request, limit: int = Query(200, ge=1, le=1000)):
    return {"items": _store(request).list_risk_checks(limit)}


@router.post("/orders")
def submit_order(req: OrderIn, request: Request):
    try:
        return _store(request).submit_paper_order(
            req.plan_id, req.snapshot, signal_id=req.signal_id,
            client_order_id=req.client_order_id, idempotency_key=req.idempotency_key,
        )
    except Exception as exc:
        raise _write_error(exc) from exc


@router.get("/orders")
def list_orders(request: Request, limit: int = Query(200, ge=1, le=1000)):
    return {"items": _store(request).list_orders(limit)}


@router.post("/orders/{order_id}/transition")
def transition_order(order_id: str, req: OrderTransitionIn, request: Request):
    try:
        return {"item": _store(request).transition_order(
            order_id, req.status, expected_revision=req.expected_revision,
            reason=req.reason, idempotency_key=req.idempotency_key,
        )}
    except Exception as exc:
        raise _write_error(exc) from exc


@router.post("/orders/{order_id}/fills")
def simulate_fill(order_id: str, req: FillIn, request: Request):
    try:
        return _store(request).simulate_fill(order_id, req.model_dump(exclude_none=True), idempotency_key=req.idempotency_key)
    except Exception as exc:
        raise _write_error(exc) from exc


@router.get("/fills")
def list_fills(request: Request, limit: int = Query(200, ge=1, le=1000)):
    return {"items": _store(request).list_fills(limit)}


@router.get("/positions")
def list_positions(request: Request):
    return {"items": _store(request).list_positions()}


@router.post("/positions/settle")
def settle_positions(as_of: str, request: Request):
    try:
        return {"released": _store(request).settle_positions(as_of)}
    except Exception as exc:
        raise _write_error(exc) from exc


@router.get("/outbox")
def list_outbox(request: Request, status: str | None = None, limit: int = Query(200, ge=1, le=1000)):
    if status and status not in OUTBOX_STATUSES:
        raise HTTPException(status_code=400, detail="无效的 Outbox 状态")
    return {"items": _store(request).list_outbox(status, limit)}


@router.patch("/outbox/{event_id}")
def update_outbox(event_id: str, req: OutboxIn, request: Request):
    try:
        return {"item": _store(request).update_outbox(event_id, req.status, req.error)}
    except Exception as exc:
        raise _write_error(exc) from exc


@router.get("/reviews")
def list_reviews(request: Request, limit: int = Query(100, ge=1, le=500)):
    return {"items": _store(request).list_daily_reviews(limit)}


@router.post("/reviews")
def create_review(req: ReviewIn, request: Request):
    try:
        return {"item": _store(request).create_daily_review(req.as_of, req.summary, idempotency_key=req.idempotency_key)}
    except Exception as exc:
        raise _write_error(exc) from exc
