"""Minimal broker protocol shared by mock and future vendor adapters.

This module is intentionally dependency-free.  A real QMT implementation must
implement these contracts in an isolated agent and must not leak vendor types
into the application or paper OMS.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

Side = Literal["buy", "sell"]
OrderStatus = Literal[
    "accepted", "partially_filled", "filled", "cancelled", "rejected"
]
ConnectionStatus = Literal["disconnected", "connecting", "connected", "degraded", "blocked"]
ExecutionMode = Literal["HUMAN_CONFIRM", "LIVE_SHADOW", "AUTO"]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class BrokerError(RuntimeError):
    """Base error for adapter and agent boundary failures."""

    def __init__(self, message: str, *, code: str = "BROKER_ERROR") -> None:
        super().__init__(message)
        self.code = code


class BrokerSafetyError(BrokerError):
    """Raised when the safety controller refuses a broker action."""


@dataclass(frozen=True)
class BrokerStatus:
    adapter: str
    connection: ConnectionStatus
    mode: ExecutionMode
    agent_pid: int | None
    sdk_configured: bool
    network_enabled: bool
    real_order_enabled: bool
    kill_switch: bool
    last_error: str | None = None
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuoteSnapshot:
    symbol: str
    last_price: float | None
    bid_price: float | None
    ask_price: float | None
    bid_quantity: float | None
    ask_quantity: float | None
    as_of: str
    quality: Literal["FRESH", "STALE", "UNAVAILABLE", "INVALID"]
    provenance: dict[str, Any]
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrderRequest:
    client_order_id: str
    symbol: str
    side: Side
    quantity: float
    limit_price: float
    order_type: Literal["limit"] = "limit"
    human_confirmed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrokerOrder:
    id: str
    client_order_id: str
    symbol: str
    side: Side
    quantity: float
    limit_price: float
    order_type: str
    status: OrderStatus
    filled_quantity: float
    avg_fill_price: float | None
    created_at: str
    updated_at: str
    provenance: dict[str, Any]
    reject_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrokerFill:
    id: str
    order_id: str
    client_order_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    trade_date: str
    occurred_at: str
    status: Literal["confirmed"]
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    cash: float
    equity: float
    available_cash: float
    as_of: str
    quality: Literal["FRESH", "STALE", "UNAVAILABLE", "INVALID"]
    provenance: dict[str, Any]
    positions: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["positions"] = list(self.positions)
        return result


class BrokerAdapter(Protocol):
    """Small side-effect boundary consumed by the Agent Core."""

    name: str

    def connect(self) -> BrokerStatus: ...

    def disconnect(self) -> BrokerStatus: ...

    def status(self) -> BrokerStatus: ...

    def get_quote(self, symbol: str) -> QuoteSnapshot: ...

    def submit_order(self, request: OrderRequest) -> BrokerOrder: ...

    def cancel_order(self, order_id: str) -> BrokerOrder: ...

    def list_orders(self) -> list[BrokerOrder]: ...

    def list_fills(self) -> list[BrokerFill]: ...

    def account_snapshot(self) -> AccountSnapshot: ...

    def positions_snapshot(self) -> list[dict[str, Any]]: ...
