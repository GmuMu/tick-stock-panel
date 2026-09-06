"""Deterministic account/order/fill/position reconciliation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReconcileReport:
    status: str
    checked_at: str
    mismatches: tuple[dict[str, Any], ...]
    broker_snapshot: dict[str, Any]
    local_snapshot: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checked_at": self.checked_at,
            "mismatches": list(self.mismatches),
            "broker_snapshot": self.broker_snapshot,
            "local_snapshot": self.local_snapshot,
        }


class ReconcileService:
    """Compare normalized snapshots without mutating OMS or broker state."""

    def compare(
        self,
        broker_snapshot: dict[str, Any] | None,
        local_snapshot: dict[str, Any] | None,
        *,
        checked_at: str,
    ) -> ReconcileReport:
        broker = broker_snapshot or {}
        local = local_snapshot or {}
        mismatches: list[dict[str, Any]] = []
        if not broker or broker.get("quality") == "UNAVAILABLE":
            mismatches.append({"code": "BROKER_SNAPSHOT_UNAVAILABLE", "message": "券商快照不可用"})
        else:
            self._compare_number(mismatches, "cash", broker.get("cash"), local.get("cash"))
            self._compare_number(mismatches, "equity", broker.get("equity"), local.get("equity"))
            self._compare_map(mismatches, "orders", broker.get("orders", []), local.get("orders", []), "client_order_id")
            self._compare_map(mismatches, "fills", broker.get("fills", []), local.get("fills", []), "id")
            self._compare_map(mismatches, "positions", broker.get("positions", []), local.get("positions", []), "symbol")
        return ReconcileReport(
            status="matched" if not mismatches else "mismatched",
            checked_at=checked_at,
            mismatches=tuple(mismatches),
            broker_snapshot=broker,
            local_snapshot=local,
        )

    @staticmethod
    def _compare_number(items: list[dict[str, Any]], field: str, left: Any, right: Any) -> None:
        if right is None:
            return
        try:
            if abs(float(left) - float(right)) > 1e-6:
                items.append({"code": "VALUE_MISMATCH", "field": field, "broker": left, "local": right})
        except (TypeError, ValueError):
            items.append({"code": "VALUE_INVALID", "field": field, "broker": left, "local": right})

    def _compare_map(
        self,
        items: list[dict[str, Any]],
        field: str,
        broker_items: Any,
        local_items: Any,
        key: str,
    ) -> None:
        broker_map = {str(item.get(key)): item for item in broker_items or [] if isinstance(item, dict)}
        local_map = {str(item.get(key)): item for item in local_items or [] if isinstance(item, dict)}
        for item_key in sorted(set(broker_map) | set(local_map)):
            if item_key not in broker_map or item_key not in local_map:
                items.append({"code": "ITEM_MISSING", "field": field, "key": item_key, "broker": broker_map.get(item_key), "local": local_map.get(item_key)})
                continue
            broker_item = broker_map[item_key]
            local_item = local_map[item_key]
            for compare_key in ("status", "quantity", "filled_quantity", "avg_cost", "available_quantity"):
                if compare_key not in broker_item or compare_key not in local_item:
                    continue
                if compare_key in {"quantity", "filled_quantity", "avg_cost", "available_quantity"}:
                    try:
                        equal = abs(float(broker_item[compare_key]) - float(local_item[compare_key])) <= 1e-6
                    except (TypeError, ValueError):
                        equal = False
                else:
                    equal = broker_item[compare_key] == local_item[compare_key]
                if not equal:
                    items.append({"code": "ITEM_MISMATCH", "field": field, "key": item_key, "attribute": compare_key, "broker": broker_item[compare_key], "local": local_item[compare_key]})
