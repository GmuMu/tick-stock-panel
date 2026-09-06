"""Application runtime for the safe Broker/QMT boundary."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from app.broker.adapters import QmtQuoteAdapter, QmtTradeAdapter, UnconfiguredQmtAdapter
from app.broker.agent import FULL_AGENT_ACTIONS, QmtAgentCore, agent_metadata
from app.broker.external_agent import ExternalAgentConfig, ExternalQmtAgentClient
from app.broker.mock import MockBroker
from app.broker.protocol import BrokerError, BrokerSafetyError, OrderRequest, utc_now
from app.broker.reconcile import ReconcileService
from app.broker.safety import SafetyController
from app.services.account_reconcile import AccountReconcileService
from app.services.human_confirm import HumanConfirmStore
from app.services.live_shadow import LiveShadowRunner
from app.services.small_live_preflight import SmallLivePreflightService


class BrokerRuntime:
    """Owns one isolated adapter and exposes normalized snapshots to the API."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.safety = SafetyController(self.data_dir)
        self.mock = MockBroker()
        self.agent = QmtAgentCore(self.mock, allowed_actions=FULL_AGENT_ACTIONS)
        self.quote_adapter = QmtQuoteAdapter(self.agent)
        self.trade_adapter = QmtTradeAdapter(self.agent, self.safety)
        try:
            self.qmt_agent_config = ExternalAgentConfig.from_environment()
            self.qmt_agent = (
                ExternalQmtAgentClient(self.qmt_agent_config)
                if self.qmt_agent_config is not None
                else None
            )
            self._qmt_config_error: str | None = None
        except BrokerError as exc:
            self.qmt_agent_config = None
            self.qmt_agent = None
            self._qmt_config_error = str(exc)
        self.qmt_quote_adapter = QmtQuoteAdapter(self.qmt_agent) if self.qmt_agent else None
        self.qmt_trade_adapter = (
            QmtTradeAdapter(self.qmt_agent, self.safety) if self.qmt_agent else None
        )
        self._qmt_live_order_enabled = os.environ.get(
            "QMT_LIVE_ORDER_ENABLED", "",
        ).strip().lower() in {"1", "true", "yes"}
        self.unconfigured_qmt = UnconfiguredQmtAdapter()
        self.reconcile = ReconcileService()
        self.account_reconcile = AccountReconcileService(self.data_dir)
        self.confirmations = HumanConfirmStore(self.data_dir)
        self.live_shadow = LiveShadowRunner()
        self.small_live_preflight = SmallLivePreflightService(self)
        self._active = "mock"
        self._last_error: str | None = None
        self._lock = threading.RLock()
        self._events_path = self.data_dir / "user_data" / "broker_agent_events.jsonl"
        self._events_path.parent.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        with self._lock:
            base = self.mock.status().to_dict() if self._active == "mock" else self._external_qmt_status()
            safety = self.safety.state()
            if self._active == "qmt":
                agent = {
                    "pid": base.get("agent_pid"),
                    "transport": "external-stdio-jsonl",
                    "vendor_sdk_loaded": bool(base.get("sdk_configured")),
                    "isolated": True,
                    "default_permission": "read_only",
                }
            else:
                agent = {**agent_metadata(), "isolated": True}
            return {
                "adapter": self._active,
                "connection": base.get("connection", "blocked"),
                "mode": safety["mode"],
                "agent": agent,
                "sdk_configured": bool(base.get("sdk_configured")),
                "network_enabled": bool(base.get("network_enabled")),
                "agent_order_enabled": bool(base.get("real_order_enabled")),
                "live_order_configured": self._qmt_live_order_enabled,
                "real_order_enabled": bool(
                    base.get("real_order_enabled")
                    and self._qmt_live_order_enabled
                    and safety["real_order_enabled"]
                ) if self._active == "qmt" else False,
                "kill_switch": safety["kill_switch"],
                "safety": safety,
                "last_error": self._last_error or base.get("last_error"),
                "contract_version": "1.0",
                "updated_at": utc_now(),
            }

    def connect(self, adapter: str = "mock", mode: str = "HUMAN_CONFIRM") -> dict[str, Any]:
        with self._lock:
            if mode not in {"HUMAN_CONFIRM", "LIVE_SHADOW"}:
                if mode == "AUTO":
                    self.safety.set_mode(mode)  # raises AUTO_DISABLED
                raise BrokerError("仅支持 HUMAN_CONFIRM 或 LIVE_SHADOW", code="MODE_INVALID")
            self.safety.set_mode(mode)  # type: ignore[arg-type]
            if adapter == "qmt":
                self._active = "qmt"
                if self.qmt_agent is None:
                    self._last_error = self._qmt_config_error or "真实 QMT Agent 未配置; 已保持 blocked"
                    self._audit("connect_blocked", {"adapter": adapter, "mode": mode})
                    return self.status()
                try:
                    self.qmt_agent.dispatch({"action": "connect"})
                except BrokerError as exc:
                    self._last_error = str(exc)
                    self._audit("connect_failed", {"adapter": adapter, "mode": mode, "code": exc.code})
                else:
                    self._last_error = None
                    self._audit("connect", {"adapter": adapter, "mode": mode})
                return self.status()
            if adapter != "mock":
                raise BrokerError("未知 Broker 适配器", code="ADAPTER_INVALID")
            self._active = "mock"
            result = self.mock.connect().to_dict()
            self._last_error = None
            self._audit("connect", {"adapter": adapter, "mode": mode})
            return self.status() | {"connection_detail": result}

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            if self._active == "mock":
                self.mock.disconnect()
            elif self.qmt_agent is not None:
                try:
                    self.qmt_agent.dispatch({"action": "disconnect"})
                except BrokerError as exc:
                    self._last_error = str(exc)
                self.safety.set_real_order_enabled(False)
                # Keep the external process available for a status query; it
                # is fully terminated during application shutdown.
            self._audit("disconnect", {"adapter": self._active})
            return self.status()

    def quote(self, symbol: str) -> dict[str, Any]:
        if self._active == "mock":
            return self.quote_adapter.get(symbol)
        if self.qmt_quote_adapter is not None:
            return self.qmt_quote_adapter.get(symbol)
        return self.unconfigured_qmt.get_quote(symbol).to_dict()

    def seed_quote(self, symbol: str, last_price: float, **kwargs: Any) -> dict[str, Any]:
        if self._active != "mock":
            raise BrokerError("当前适配器不是 mock, 禁止注入行情", code="ADAPTER_BLOCKED")
        quote = self.mock.seed_quote(symbol, last_price, **kwargs)
        self._audit("quote_seeded", quote.to_dict())
        return quote.to_dict()

    def submit(self, request: OrderRequest, *, confirmation_id: str | None = None) -> dict[str, Any]:
        if self._active == "qmt":
            if self.qmt_trade_adapter is None:
                raise BrokerError("真实 QMT Agent 未配置", code="QMT_NOT_CONFIGURED")
            if not self.status()["real_order_enabled"]:
                raise BrokerSafetyError(
                    "真实 QMT 下单开关未启用; 先完成 Small Live 审批",
                    code="QMT_LIVE_DISABLED",
                )
            if self.safety.state()["mode"] == "HUMAN_CONFIRM":
                if confirmation_id:
                    self.confirmations.authorize(
                        confirmation_id,
                        "broker.submit_order",
                        request.to_dict(),
                    )
                    request = OrderRequest(**{**request.to_dict(), "human_confirmed": True})
                elif not request.human_confirmed:
                    raise BrokerSafetyError(
                        "HUMAN_CONFIRM 模式需要人工确认",
                        code="HUMAN_CONFIRM_REQUIRED",
                    )
            result = self.qmt_trade_adapter.submit(
                request,
                connected=self._external_qmt_status().get("connection") == "connected",
                real_order_required=True,
            )
            self._audit("qmt_order_submitted", result)
            return result
        if self._active != "mock":
            raise BrokerError("真实 QMT 交易适配器未配置", code="QMT_NOT_CONFIGURED")
        if self.safety.state()["mode"] == "HUMAN_CONFIRM":
            if confirmation_id:
                self.confirmations.authorize(
                    confirmation_id,
                    "broker.submit_order",
                    request.to_dict(),
                )
                request = OrderRequest(**{**request.to_dict(), "human_confirmed": True})
            elif not request.human_confirmed:
                # Keep the protocol-level flag for local callers while the API
                # uses the stronger persisted confirmation flow.
                raise BrokerSafetyError("HUMAN_CONFIRM 模式需要人工确认", code="HUMAN_CONFIRM_REQUIRED")
        result = self.trade_adapter.submit(request, connected=self.mock.status().connection == "connected")
        self._audit("order_submitted", result)
        return result

    def cancel(self, order_id: str) -> dict[str, Any]:
        if self._active == "qmt":
            if self.qmt_trade_adapter is None:
                raise BrokerError("真实 QMT Agent 未配置", code="QMT_NOT_CONFIGURED")
            if not self.status()["real_order_enabled"]:
                raise BrokerSafetyError(
                    "真实 QMT 撤单开关未启用; 先完成 Small Live 审批",
                    code="QMT_LIVE_DISABLED",
                )
            result = self.qmt_trade_adapter.cancel(
                order_id,
                connected=self._external_qmt_status().get("connection") == "connected",
                real_order_required=True,
            )
            self._audit("qmt_order_cancelled", result)
            return result
        if self._active != "mock":
            raise BrokerError("真实 QMT 交易适配器未配置", code="QMT_NOT_CONFIGURED")
        result = self.trade_adapter.cancel(order_id, connected=self.mock.status().connection == "connected")
        self._audit("order_cancelled", result)
        return result

    def simulate_fill(self, order_id: str, quantity: float, price: float, trade_date: str | None = None) -> dict[str, Any]:
        if self._active != "mock":
            raise BrokerError("只有 mock broker 支持显式模拟成交", code="SIMULATION_ONLY")
        fill = self.mock.simulate_fill(order_id, quantity, price, trade_date=trade_date)
        self._audit("fill_simulated", fill.to_dict())
        return fill.to_dict()

    def orders(self) -> list[dict[str, Any]]:
        if self._active == "mock":
            return [item.to_dict() for item in self.mock.list_orders()]
        if self.qmt_agent is not None:
            return self.qmt_agent.dispatch({"action": "orders"})["result"]
        return []

    def fills(self) -> list[dict[str, Any]]:
        if self._active == "mock":
            return [item.to_dict() for item in self.mock.list_fills()]
        if self.qmt_agent is not None:
            return self.qmt_agent.dispatch({"action": "fills"})["result"]
        return []

    def account(self) -> dict[str, Any]:
        if self._active == "mock":
            return self.mock.account_snapshot().to_dict()
        if self.qmt_agent is not None:
            return self.qmt_agent.dispatch({"action": "account"})["result"]
        return {"quality": "UNAVAILABLE"}

    def reconcile_snapshot(self, local_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        broker = self._snapshot()
        local = local_snapshot if local_snapshot is not None else broker
        record = self.account_reconcile.run(broker, local)
        self._audit("reconcile", record)
        return {**record["report"], "id": record["id"], "created_at": record["created_at"]}

    def list_reconciliations(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.account_reconcile.list(limit)

    def request_confirmation(
        self, action: str, payload: dict[str, Any], ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        result = self.confirmations.request(action, payload, ttl_seconds)
        self._audit("confirmation_requested", result)
        return result

    def list_confirmations(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.confirmations.list(limit)

    def decide_confirmation(
        self, confirmation_id: str, status: str, decided_by: str = "local-user",
    ) -> dict[str, Any]:
        result = self.confirmations.decide(confirmation_id, status, decided_by)
        self._audit("confirmation_decided", result)
        return result

    def run_live_shadow(
        self, request: OrderRequest, *, simulate_fill: bool = False,
    ) -> dict[str, Any]:
        result = self.live_shadow.run(self, request, simulate_fill=simulate_fill)
        self._audit("live_shadow", result)
        return result

    def run_small_live_preflight(self, symbol: str) -> dict[str, Any]:
        return self.small_live_preflight.run(symbol)

    def list_small_live_preflights(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.small_live_preflight.list(limit)

    def activate_small_live(
        self,
        preflight_id: str,
        confirmation_id: str,
    ) -> dict[str, Any]:
        if self._active != "qmt" or self.qmt_agent is None:
            raise BrokerSafetyError(
                "只有已连接的 QMT Agent 可以激活 Small Live",
                code="QMT_LIVE_NOT_READY",
            )
        preflight = next(
            (
                item for item in self.small_live_preflight.list(500)
                if item.get("id") == preflight_id
            ),
            None,
        )
        if preflight is None:
            raise BrokerSafetyError("Small Live 预检记录不存在", code="PREFLIGHT_NOT_FOUND")
        if preflight.get("status") != "READY_FOR_REVIEW":
            raise BrokerSafetyError(
                "Small Live 预检尚未通过",
                code="PREFLIGHT_BLOCKED",
            )
        external = self._external_qmt_status()
        if external.get("connection") != "connected" or not external.get("real_order_enabled"):
            raise BrokerSafetyError(
                "QMT Agent 尚未开启下单能力",
                code="QMT_AGENT_ORDERS_DISABLED",
            )
        if not self._qmt_live_order_enabled:
            raise BrokerSafetyError(
                "应用侧 QMT_LIVE_ORDER_ENABLED 未开启",
                code="QMT_LIVE_DISABLED",
            )
        self.confirmations.authorize(
            confirmation_id,
            "broker.enable_small_live",
            {"preflight_id": preflight_id, "symbol": preflight["symbol"]},
        )
        self.safety.set_real_order_enabled(True)
        result = self.status()
        self._audit(
            "small_live_activated",
            {"preflight_id": preflight_id, "symbol": preflight["symbol"]},
        )
        return result

    def deactivate_small_live(self, reason: str = "manual deactivation") -> dict[str, Any]:
        self.safety.set_real_order_enabled(False)
        self._audit("small_live_deactivated", {"reason": reason})
        return self.status()

    def close(self) -> None:
        if self.qmt_agent is not None:
            self.qmt_agent.close()

    def trip_kill_switch(self, reason: str) -> dict[str, Any]:
        result = self.safety.trip(reason)
        self._audit("kill_switch_on", result)
        return self.status()

    def reset_kill_switch(self) -> dict[str, Any]:
        result = self.safety.reset()
        self._audit("kill_switch_off", result)
        return self.status()

    def set_mode(self, mode: str) -> dict[str, Any]:
        result = self.safety.set_mode(mode)  # type: ignore[arg-type]
        self._audit("mode_changed", result)
        return self.status()

    def _snapshot(self) -> dict[str, Any]:
        account = self.account()
        return {
            "quality": account.get("quality", "UNAVAILABLE"),
            "cash": account.get("cash"),
            "equity": account.get("equity"),
            "orders": self.orders(),
            "fills": self.fills(),
            "positions": account.get("positions", []),
        }

    def _external_qmt_status(self) -> dict[str, Any]:
        if self.qmt_agent is None:
            base = self.unconfigured_qmt.status().to_dict()
            if self._qmt_config_error:
                base["last_error"] = self._qmt_config_error
            return base
        try:
            return self.qmt_agent.dispatch({"action": "status"})["result"]
        except BrokerError as exc:
            return {
                **self.unconfigured_qmt.status().to_dict(),
                "last_error": str(exc),
            }

    def _audit(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {"event_type": event_type, "occurred_at": utc_now(), "payload": payload}
        with self._events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
