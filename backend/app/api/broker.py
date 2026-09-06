"""Safe Broker/QMT boundary API for Phase 11.

Only the local mock adapter is executable in this phase.  Selecting ``qmt``
returns an explicit blocked status and never imports or calls a real SDK.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.broker.protocol import BrokerError, OrderRequest
from app.broker.runtime import BrokerRuntime

router = APIRouter(prefix="/api/broker", tags=["broker-qmt"])


def _runtime(request: Request) -> BrokerRuntime:
    runtime = getattr(request.app.state, "broker_runtime", None)
    if runtime is None:
        data_dir = request.app.state.repo.store.data_dir
        runtime = BrokerRuntime(data_dir)
        request.app.state.broker_runtime = runtime
    return runtime


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, BrokerError):
        status = 409 if exc.code in {
            "KILL_SWITCH_ACTIVE", "HUMAN_CONFIRM_REQUIRED", "AUTO_DISABLED",
            "BROKER_DISCONNECTED", "CONFIRM_NOT_APPROVED", "CONFIRM_NOT_PENDING",
            "CONFIRM_PAYLOAD_MISMATCH",
        } else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})
    return HTTPException(status_code=500, detail={"code": "BROKER_INTERNAL_ERROR", "message": str(exc)})


class ConnectIn(BaseModel):
    adapter: Literal["mock", "qmt"] = "mock"
    mode: Literal["HUMAN_CONFIRM", "LIVE_SHADOW", "AUTO"] = "HUMAN_CONFIRM"


class ModeIn(BaseModel):
    mode: Literal["HUMAN_CONFIRM", "LIVE_SHADOW", "AUTO"]


class QuoteSeedIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    last_price: float = Field(gt=0)
    bid_price: float | None = Field(default=None, gt=0)
    ask_price: float | None = Field(default=None, gt=0)
    as_of: str | None = Field(default=None, max_length=40)


class BrokerOrderIn(BaseModel):
    client_order_id: str = Field(min_length=1, max_length=160)
    symbol: str = Field(min_length=1, max_length=32)
    side: Literal["buy", "sell"]
    quantity: float = Field(gt=0)
    limit_price: float = Field(gt=0)
    order_type: Literal["limit"] = "limit"
    human_confirmed: bool = False
    confirmation_id: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FillIn(BaseModel):
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    trade_date: str | None = Field(default=None, max_length=40)


class KillSwitchIn(BaseModel):
    reason: str = Field(default="manual kill switch", min_length=1, max_length=500)


class ReconcileIn(BaseModel):
    local_snapshot: dict[str, Any] | None = None


class ConfirmationIn(BaseModel):
    action: str = Field(min_length=1, max_length=160)
    payload: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int = Field(default=300, ge=30, le=3600)


class ConfirmationDecisionIn(BaseModel):
    status: Literal["approved", "rejected"]
    decided_by: str = Field(default="local-user", min_length=1, max_length=160)


class LiveShadowIn(BrokerOrderIn):
    simulate_fill: bool = False


@router.get("/status")
def status(request: Request):
    return _runtime(request).status()


@router.post("/connect")
def connect(req: ConnectIn, request: Request):
    try:
        return _runtime(request).connect(req.adapter, req.mode)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/disconnect")
def disconnect(request: Request):
    try:
        return _runtime(request).disconnect()
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/mode")
def set_mode(req: ModeIn, request: Request):
    try:
        return _runtime(request).set_mode(req.mode)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/quote")
def quote(request: Request, symbol: str = Query(min_length=1, max_length=32)):
    try:
        return _runtime(request).quote(symbol)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/quote/seed")
def seed_quote(req: QuoteSeedIn, request: Request):
    try:
        return _runtime(request).seed_quote(
            req.symbol, req.last_price, bid_price=req.bid_price, ask_price=req.ask_price, as_of=req.as_of,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/orders")
def orders(request: Request):
    return {"items": _runtime(request).orders()}


@router.post("/orders")
def submit_order(req: BrokerOrderIn, request: Request):
    try:
        payload = req.model_dump()
        confirmation_id = payload.pop("confirmation_id", None)
        if _runtime(request).status()["mode"] == "HUMAN_CONFIRM" and not confirmation_id:
            raise BrokerError("HUMAN_CONFIRM 模式必须先创建并批准确认请求", code="HUMAN_CONFIRM_REQUIRED")
        return {"item": _runtime(request).submit(OrderRequest(**payload), confirmation_id=confirmation_id)}
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str, request: Request):
    try:
        return {"item": _runtime(request).cancel(order_id)}
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/fills")
def fills(request: Request):
    return {"items": _runtime(request).fills()}


@router.post("/orders/{order_id}/fills")
def simulate_fill(order_id: str, req: FillIn, request: Request):
    try:
        return {"item": _runtime(request).simulate_fill(order_id, req.quantity, req.price, req.trade_date)}
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/account")
def account(request: Request):
    return _runtime(request).account()


@router.post("/reconcile")
def reconcile(req: ReconcileIn, request: Request):
    try:
        return _runtime(request).reconcile_snapshot(req.local_snapshot)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/reconciliations")
def reconciliations(request: Request, limit: int = Query(100, ge=1, le=500)):
    return {"items": _runtime(request).list_reconciliations(limit)}


@router.get("/confirmations")
def confirmations(request: Request, limit: int = Query(100, ge=1, le=500)):
    return {"items": _runtime(request).list_confirmations(limit)}


@router.post("/confirmations")
def request_confirmation(req: ConfirmationIn, request: Request):
    try:
        return _runtime(request).request_confirmation(req.action, req.payload, req.ttl_seconds)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/confirmations/{confirmation_id}/decision")
def decide_confirmation(confirmation_id: str, req: ConfirmationDecisionIn, request: Request):
    try:
        return _runtime(request).decide_confirmation(confirmation_id, req.status, req.decided_by)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/live-shadow/run")
def live_shadow(req: LiveShadowIn, request: Request):
    try:
        payload = req.model_dump()
        simulate_fill = bool(payload.pop("simulate_fill", False))
        payload.pop("confirmation_id", None)
        return _runtime(request).run_live_shadow(
            OrderRequest(**payload), simulate_fill=simulate_fill,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/safety")
def safety(request: Request):
    return _runtime(request).status()["safety"]


@router.post("/safety/kill")
def kill(req: KillSwitchIn, request: Request):
    return _runtime(request).trip_kill_switch(req.reason)


@router.post("/safety/reset")
def reset(request: Request):
    return _runtime(request).reset_kill_switch()
