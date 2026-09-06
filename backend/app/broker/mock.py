"""Deterministic in-process broker used by tests and the local Phase 11 UI."""
from __future__ import annotations

import threading
import uuid
from typing import Any

from app.broker.protocol import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerError,
    BrokerFill,
    BrokerOrder,
    BrokerStatus,
    OrderRequest,
    QuoteSnapshot,
    utc_now,
)


class MockBroker(BrokerAdapter):
    """A no-network broker with explicit fill injection and quote seeding."""

    name = "mock"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._connected = False
        self._quotes: dict[str, QuoteSnapshot] = {}
        self._orders: dict[str, BrokerOrder] = {}
        self._fills: list[BrokerFill] = []
        self._cash = 1_000_000.0

    def connect(self) -> BrokerStatus:
        with self._lock:
            self._connected = True
            return self.status()

    def disconnect(self) -> BrokerStatus:
        with self._lock:
            self._connected = False
            return self.status()

    def status(self) -> BrokerStatus:
        return BrokerStatus(
            adapter=self.name,
            connection="connected" if self._connected else "disconnected",
            mode="HUMAN_CONFIRM",
            agent_pid=None,
            sdk_configured=True,
            network_enabled=False,
            real_order_enabled=False,
            kill_switch=False,
        )

    def seed_quote(
        self,
        symbol: str,
        last_price: float,
        *,
        bid_price: float | None = None,
        ask_price: float | None = None,
        as_of: str | None = None,
    ) -> QuoteSnapshot:
        if last_price <= 0:
            raise BrokerError("行情价格必须为正数", code="QUOTE_INVALID")
        normalized = symbol.strip().upper()
        quote = QuoteSnapshot(
            symbol=normalized,
            last_price=float(last_price),
            bid_price=bid_price if bid_price is not None else float(last_price),
            ask_price=ask_price if ask_price is not None else float(last_price),
            bid_quantity=100.0,
            ask_quantity=100.0,
            as_of=as_of or utc_now(),
            quality="FRESH",
            provenance={"adapter": self.name, "source": "seeded_mock", "network": False},
        )
        with self._lock:
            self._quotes[normalized] = quote
        return quote

    def get_quote(self, symbol: str) -> QuoteSnapshot:
        normalized = symbol.strip().upper()
        with self._lock:
            quote = self._quotes.get(normalized)
        if quote is not None:
            return quote
        return QuoteSnapshot(
            symbol=normalized,
            last_price=None,
            bid_price=None,
            ask_price=None,
            bid_quantity=None,
            ask_quantity=None,
            as_of=utc_now(),
            quality="UNAVAILABLE",
            provenance={"adapter": self.name, "source": "seeded_mock", "network": False},
            reason="mock broker has no seeded quote",
        )

    def submit_order(self, request: OrderRequest) -> BrokerOrder:
        with self._lock:
            self._require_connected()
            if request.quantity <= 0 or request.limit_price <= 0:
                raise BrokerError("订单数量和价格必须为正数", code="ORDER_INVALID")
            if request.client_order_id in {o.client_order_id for o in self._orders.values()}:
                existing = next(o for o in self._orders.values() if o.client_order_id == request.client_order_id)
                return existing
            now = utc_now()
            order = BrokerOrder(
                id=f"brk_ord_{uuid.uuid4().hex[:12]}",
                client_order_id=request.client_order_id,
                symbol=request.symbol.strip().upper(),
                side=request.side,
                quantity=float(request.quantity),
                limit_price=float(request.limit_price),
                order_type=request.order_type,
                status="accepted",
                filled_quantity=0.0,
                avg_fill_price=None,
                created_at=now,
                updated_at=now,
                provenance={"adapter": self.name, "network": False, "simulation": True},
            )
            self._orders[order.id] = order
            return order

    def cancel_order(self, order_id: str) -> BrokerOrder:
        with self._lock:
            self._require_connected()
            order = self._orders.get(order_id)
            if order is None:
                raise BrokerError("Broker 订单不存在", code="ORDER_NOT_FOUND")
            if order.status not in {"accepted", "partially_filled"}:
                return order
            updated = BrokerOrder(**{**order.to_dict(), "status": "cancelled", "updated_at": utc_now()})
            self._orders[order_id] = updated
            return updated

    def simulate_fill(self, order_id: str, quantity: float, price: float, *, trade_date: str | None = None) -> BrokerFill:
        with self._lock:
            self._require_connected()
            order = self._orders.get(order_id)
            if order is None:
                raise BrokerError("Broker 订单不存在", code="ORDER_NOT_FOUND")
            remaining = order.quantity - order.filled_quantity
            if order.status not in {"accepted", "partially_filled"} or quantity <= 0 or quantity > remaining:
                raise BrokerError("成交数量超过订单剩余数量", code="FILL_INVALID")
            now = utc_now()
            fill = BrokerFill(
                id=f"brk_fill_{uuid.uuid4().hex[:12]}",
                order_id=order.id,
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=float(quantity),
                price=float(price),
                trade_date=trade_date or now[:10],
                occurred_at=now,
                status="confirmed",
                provenance={"adapter": self.name, "network": False, "simulation": True},
            )
            filled = order.filled_quantity + quantity
            avg = ((order.avg_fill_price or 0) * order.filled_quantity + price * quantity) / filled
            updated = BrokerOrder(**{
                **order.to_dict(),
                "status": "filled" if abs(filled - order.quantity) < 1e-9 else "partially_filled",
                "filled_quantity": filled,
                "avg_fill_price": avg,
                "updated_at": now,
            })
            self._orders[order.id] = updated
            self._fills.append(fill)
            return fill

    def list_orders(self) -> list[BrokerOrder]:
        with self._lock:
            return list(reversed(list(self._orders.values())))

    def list_fills(self) -> list[BrokerFill]:
        with self._lock:
            return list(reversed(self._fills))

    def account_snapshot(self) -> AccountSnapshot:
        positions = self.positions_snapshot()
        market_value = sum(float(item.get("quantity", 0)) * float(item.get("avg_cost", 0)) for item in positions)
        return AccountSnapshot(
            account_id="mock-account",
            cash=self._cash,
            equity=self._cash + market_value,
            available_cash=self._cash,
            as_of=utc_now(),
            quality="FRESH" if self._connected else "UNAVAILABLE",
            provenance={"adapter": self.name, "network": False, "simulation": True},
            positions=tuple(positions),
        )

    def positions_snapshot(self) -> list[dict[str, Any]]:
        positions: dict[str, dict[str, Any]] = {}
        for fill in self._fills:
            item = positions.setdefault(fill.symbol, {"symbol": fill.symbol, "quantity": 0.0, "available_quantity": 0.0, "avg_cost": 0.0})
            if fill.side == "buy":
                total = item["quantity"] * item["avg_cost"] + fill.quantity * fill.price
                item["quantity"] += fill.quantity
                item["avg_cost"] = total / item["quantity"] if item["quantity"] else 0.0
            else:
                item["quantity"] -= fill.quantity
            item["available_quantity"] = item["quantity"]
        return [item for item in positions.values() if item["quantity"] > 0]

    def _require_connected(self) -> None:
        if not self._connected:
            raise BrokerError("Broker 尚未连接", code="BROKER_DISCONNECTED")
