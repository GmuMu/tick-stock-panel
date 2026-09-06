"""Vendor-specific QMT Agent.

This module is launched in a separate process via ``QMT_AGENT_COMMAND``.
Importing the main FastAPI application never imports ``xtquant``.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from app.broker.agent import (
    FULL_AGENT_ACTIONS,
    READ_ONLY_AGENT_ACTIONS,
    QmtAgentCore,
    run_stdio_agent,
)
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


def _value(item: Any, *names: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        for name in names:
            if name in item:
                return item[name]
    else:
        for name in names:
            if hasattr(item, name):
                return getattr(item, name)
    return default


def _number(item: Any, *names: str, default: float = 0.0) -> float:
    try:
        return float(_value(item, *names, default=default) or default)
    except (TypeError, ValueError):
        return default


def _time_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="seconds")
    if isinstance(value, (int, float)) and value > 0:
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds")
        except (OverflowError, OSError, ValueError):
            return str(value)
    if value is None or value == "":
        return utc_now()
    return str(value)


class QmtVendorBroker(BrokerAdapter):
    """Small normalized adapter around the official xtquant interfaces."""

    name = "qmt"

    def __init__(self, xtdata: Any, trader: Any, account: Any, constants: Any, *, allow_orders: bool) -> None:
        self.xtdata = xtdata
        self.trader = trader
        self.account = account
        self.constants = constants
        self.allow_orders = allow_orders
        self._connected = False

    @classmethod
    def from_environment(cls) -> QmtVendorBroker:
        try:
            from xtquant import xtconstant, xtdata
            from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
            from xtquant.xttype import StockAccount
        except ImportError as exc:
            raise BrokerError(
                "独立 QMT Agent 缺少 xtquant SDK",
                code="QMT_SDK_UNAVAILABLE",
            ) from exc

        userdata_path = os.environ.get("QMT_USERDATA_PATH", "").strip()
        account_id = os.environ.get("QMT_ACCOUNT_ID", "").strip()
        if not userdata_path or not account_id:
            raise BrokerError(
                "QMT_USERDATA_PATH 和 QMT_ACCOUNT_ID 必须配置",
                code="QMT_ACCOUNT_CONFIG_REQUIRED",
            )
        try:
            session = int(os.environ.get("QMT_SESSION_ID", "9901"))
        except ValueError as exc:
            raise BrokerError("QMT_SESSION_ID 必须是整数", code="QMT_ACCOUNT_CONFIG_INVALID") from exc

        class Callback(XtQuantTraderCallback):
            def on_disconnected(self) -> None:
                return None

        trader = XtQuantTrader(userdata_path, session, Callback())
        try:
            account = StockAccount(account_id)
        except TypeError:
            account = StockAccount(account_id, "STOCK")
        allow_orders = os.environ.get("QMT_AGENT_ALLOW_ORDERS", "").strip().lower() in {
            "1", "true", "yes",
        }
        return cls(xtdata, trader, account, xtconstant, allow_orders=allow_orders)

    def connect(self) -> BrokerStatus:
        result = self.trader.connect()
        if result != 0:
            raise BrokerError(f"QMT 连接失败: {result}", code="QMT_CONNECT_FAILED")
        subscribe = getattr(self.trader, "subscribe", None)
        if callable(subscribe):
            subscribe_result = subscribe(self.account)
            if subscribe_result not in (None, 0):
                raise BrokerError(
                    f"QMT 账户订阅失败: {subscribe_result}",
                    code="QMT_SUBSCRIBE_FAILED",
                )
        self._connected = True
        return self.status()

    def disconnect(self) -> BrokerStatus:
        stop = getattr(self.trader, "stop", None)
        if callable(stop):
            stop()
        self._connected = False
        return self.status()

    def status(self) -> BrokerStatus:
        return BrokerStatus(
            adapter=self.name,
            connection="connected" if self._connected else "disconnected",
            mode="HUMAN_CONFIRM",
            agent_pid=os.getpid(),
            sdk_configured=True,
            network_enabled=True,
            real_order_enabled=self.allow_orders,
            kill_switch=False,
            last_error=None,
        )

    def get_quote(self, symbol: str) -> QuoteSnapshot:
        self._require_connected()
        normalized = symbol.strip().upper()
        payload = self.xtdata.get_full_tick([normalized]) or {}
        tick = payload.get(normalized) or {}
        last = _number(tick, "lastPrice", "last_price", default=0.0)
        quality = "FRESH" if last > 0 else "UNAVAILABLE"
        return QuoteSnapshot(
            symbol=normalized,
            last_price=last or None,
            bid_price=_number(tick, "bidPrice", "bid_price", default=0.0) or None,
            ask_price=_number(tick, "askPrice", "ask_price", default=0.0) or None,
            bid_quantity=_number(tick, "bidVol", "bid_volume", default=0.0) or None,
            ask_quantity=_number(tick, "askVol", "ask_volume", default=0.0) or None,
            as_of=_time_text(_value(tick, "time", "timestamp")),
            quality=quality,
            provenance={"adapter": self.name, "source": "xtquant", "network": True, "simulation": False},
            reason=None if quality == "FRESH" else "QMT 未返回有效最新价",
        )

    def submit_order(self, request: OrderRequest) -> BrokerOrder:
        self._require_connected()
        if not self.allow_orders:
            raise BrokerError("QMT Agent 下单权限未显式开启", code="QMT_AGENT_ORDERS_DISABLED")
        if request.quantity != int(request.quantity):
            raise BrokerError("QMT 股票订单数量必须是整数", code="ORDER_INVALID")
        order_type = self.constants.STOCK_BUY if request.side == "buy" else self.constants.STOCK_SELL
        order_id = self.trader.order_stock(
            self.account,
            request.symbol.strip().upper(),
            order_type,
            int(request.quantity),
            self.constants.FIX_PRICE,
            float(request.limit_price),
            str(request.metadata.get("strategy_name", "tick-stock-panel")),
            str(request.metadata.get("order_remark", request.client_order_id)),
        )
        if int(order_id) <= 0:
            raise BrokerError("QMT 下单失败", code="QMT_ORDER_REJECTED")
        now = utc_now()
        return BrokerOrder(
            id=str(order_id),
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
            provenance={"adapter": self.name, "source": "xtquant", "network": True, "simulation": False},
        )

    def cancel_order(self, order_id: str) -> BrokerOrder:
        self._require_connected()
        if not self.allow_orders:
            raise BrokerError("QMT Agent 撤单权限未显式开启", code="QMT_AGENT_ORDERS_DISABLED")
        result = self.trader.cancel_order_stock(self.account, int(order_id))
        if result is False or (result not in (None, 0, True)):
            raise BrokerError(f"QMT 撤单失败: {result}", code="QMT_CANCEL_REJECTED")
        now = utc_now()
        return BrokerOrder(
            id=str(order_id),
            client_order_id=f"qmt-{order_id}",
            symbol="",
            side="buy",
            quantity=0.0,
            limit_price=0.0,
            order_type="limit",
            status="cancelled",
            filled_quantity=0.0,
            avg_fill_price=None,
            created_at=now,
            updated_at=now,
            provenance={"adapter": self.name, "source": "xtquant", "network": True, "simulation": False},
        )

    def list_orders(self) -> list[BrokerOrder]:
        self._require_connected()
        return [self._order(item) for item in (self.trader.query_stock_orders(self.account) or [])]

    def list_fills(self) -> list[BrokerFill]:
        self._require_connected()
        return [self._fill(item) for item in (self.trader.query_stock_trades(self.account) or [])]

    def account_snapshot(self) -> AccountSnapshot:
        self._require_connected()
        asset = self.trader.query_stock_asset(self.account)
        if asset is None:
            raise BrokerError("QMT 账户快照为空", code="QMT_ACCOUNT_SNAPSHOT_UNAVAILABLE")
        positions = tuple(self.positions_snapshot())
        cash = _number(asset, "cash", "m_dCash", "available_cash")
        equity = _number(asset, "asset", "m_dAsset", "equity", default=cash)
        return AccountSnapshot(
            account_id=str(_value(self.account, "account_id", default="")),
            cash=cash,
            equity=equity,
            available_cash=cash,
            as_of=utc_now(),
            quality="FRESH",
            provenance={"adapter": self.name, "source": "xtquant", "network": True, "simulation": False},
            positions=positions,
        )

    def positions_snapshot(self) -> list[dict[str, Any]]:
        self._require_connected()
        rows = self.trader.query_stock_positions(self.account) or []
        return [
            {
                "symbol": str(_value(item, "stock_code", "symbol", default="")).upper(),
                "quantity": _number(item, "volume", "quantity", default=0.0),
                "available_quantity": _number(item, "can_use_volume", "available_quantity", default=0.0),
                "avg_cost": _number(item, "open_price", "avg_cost", default=0.0),
            }
            for item in rows
        ]

    def _order(self, item: Any) -> BrokerOrder:
        order_type = _value(item, "order_type", default=self.constants.STOCK_BUY)
        side = "buy" if order_type == self.constants.STOCK_BUY else "sell"
        status = _value(item, "order_status", "status", default=self.constants.ORDER_UNKNOWN)
        status_map = {
            getattr(self.constants, "ORDER_SUCCEEDED", 56): "filled",
            getattr(self.constants, "ORDER_CANCELED", 54): "cancelled",
            getattr(self.constants, "ORDER_JUNK", 57): "rejected",
            getattr(self.constants, "ORDER_PART_SUCC", 55): "partially_filled",
        }
        normalized_status = status_map.get(status, "accepted")
        order_id = str(_value(item, "order_id", "id", default=""))
        return BrokerOrder(
            id=order_id,
            client_order_id=str(_value(item, "order_remark", default=f"qmt-{order_id}")),
            symbol=str(_value(item, "stock_code", "symbol", default="")).upper(),
            side=side,
            quantity=_number(item, "order_volume", "quantity"),
            limit_price=_number(item, "price", "limit_price"),
            order_type="limit",
            status=normalized_status,
            filled_quantity=_number(item, "traded_volume", "filled_quantity"),
            avg_fill_price=_number(item, "traded_price", "avg_fill_price") or None,
            created_at=_time_text(_value(item, "order_time", "created_at")),
            updated_at=_time_text(_value(item, "update_time", "updated_at")),
            provenance={"adapter": self.name, "source": "xtquant", "network": True, "simulation": False},
        )

    def _fill(self, item: Any) -> BrokerFill:
        order_type = _value(item, "order_type", default=self.constants.STOCK_BUY)
        side = "buy" if order_type == self.constants.STOCK_BUY else "sell"
        fill_id = str(_value(item, "traded_id", "trade_id", "id", default=""))
        order_id = str(_value(item, "order_id", default=""))
        return BrokerFill(
            id=fill_id,
            order_id=order_id,
            client_order_id=f"qmt-{order_id}",
            symbol=str(_value(item, "stock_code", "symbol", default="")).upper(),
            side=side,
            quantity=_number(item, "traded_volume", "quantity"),
            price=_number(item, "traded_price", "price"),
            trade_date=_time_text(_value(item, "traded_time", "trade_date"))[:10],
            occurred_at=_time_text(_value(item, "traded_time", "occurred_at")),
            status="confirmed",
            provenance={"adapter": self.name, "source": "xtquant", "network": True, "simulation": False},
        )

    def _require_connected(self) -> None:
        if not self._connected:
            raise BrokerError("QMT Agent 尚未连接", code="BROKER_DISCONNECTED")


def _run_unavailable_agent(exc: Exception) -> None:
    import json
    import sys

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            command = json.loads(line)
            response = {
                "id": command.get("id"),
                "ok": False,
                "error": str(exc),
                "code": getattr(exc, "code", "QMT_AGENT_UNAVAILABLE"),
            }
        except Exception:
            response = {"ok": False, "error": str(exc), "code": "QMT_AGENT_UNAVAILABLE"}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main() -> None:
    try:
        broker = QmtVendorBroker.from_environment()
    except Exception as exc:
        _run_unavailable_agent(exc)
        return
    allowed_actions = FULL_AGENT_ACTIONS if broker.allow_orders else READ_ONLY_AGENT_ACTIONS
    run_stdio_agent(QmtAgentCore(broker, allowed_actions=allowed_actions))


if __name__ == "__main__":
    main()
