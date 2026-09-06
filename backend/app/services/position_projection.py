"""Deterministic position projection fed only by confirmed paper fills."""
from __future__ import annotations

from typing import Any


def project_fill(position: dict[str, Any] | None, fill: dict[str, Any]) -> dict[str, Any]:
    current = dict(position or {})
    quantity = float(current.get("quantity") or 0)
    available = float(current.get("available_quantity") or 0)
    avg_cost = float(current.get("avg_cost") or 0)
    realized = float(current.get("realized_pnl") or 0)
    fill_qty = float(fill["quantity"])
    price = float(fill["price"])
    side = str(fill["side"]).lower()
    if fill_qty <= 0 or price <= 0 or side not in {"buy", "sell"}:
        raise ValueError("成交回报必须包含有效方向、数量和价格")
    if side == "buy":
        total_cost = quantity * avg_cost + fill_qty * price
        quantity += fill_qty
        avg_cost = total_cost / quantity if quantity else 0
        # A 股买入当日不可卖, settlement is an explicit later projection step.
        available = available
    else:
        if fill_qty > available:
            raise ValueError("成交数量超过可卖持仓")
        realized += (price - avg_cost) * fill_qty
        quantity -= fill_qty
        available -= fill_qty
        if quantity <= 0:
            quantity = 0
            available = 0
            avg_cost = 0
    return {
        "symbol": str(fill["symbol"]),
        "quantity": quantity,
        "available_quantity": available,
        "avg_cost": avg_cost,
        "realized_pnl": realized,
        "last_fill_id": fill["id"],
        "as_of": str(fill.get("trade_date") or fill.get("occurred_at") or ""),
    }
