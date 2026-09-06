"""QMT-shaped adapters backed by the isolated Agent Core.

The names intentionally match the eventual integration points while the
current implementation remains mock-only and network-free.
"""
from __future__ import annotations

from typing import Any

from app.broker.agent import QmtAgentCore
from app.broker.protocol import (
    BrokerError,
    BrokerStatus,
    OrderRequest,
    QuoteSnapshot,
)
from app.broker.safety import SafetyController


class QmtQuoteAdapter:
    name = "qmt-quote"

    def __init__(self, agent: QmtAgentCore) -> None:
        self.agent = agent

    def get(self, symbol: str) -> dict[str, Any]:
        response = self.agent.dispatch({"action": "quote", "symbol": symbol})
        return response["result"]


class QmtTradeAdapter:
    name = "qmt-trade"

    def __init__(self, agent: QmtAgentCore, safety: SafetyController) -> None:
        self.agent = agent
        self.safety = safety

    def submit(
        self,
        request: OrderRequest,
        *,
        connected: bool,
        real_order_required: bool = False,
    ) -> dict[str, Any]:
        self.safety.assert_can_trade(
            connected=connected,
            human_confirmed=request.human_confirmed,
            real_order_required=real_order_required,
        )
        return self.agent.dispatch({"action": "submit_order", "order": request.to_dict()})["result"]

    def cancel(
        self,
        order_id: str,
        *,
        connected: bool,
        real_order_required: bool = False,
    ) -> dict[str, Any]:
        self.safety.assert_can_trade(
            connected=connected,
            human_confirmed=True,
            real_order_required=real_order_required,
        )
        return self.agent.dispatch({"action": "cancel_order", "order_id": order_id})["result"]


class UnconfiguredQmtAdapter:
    """Explicitly unavailable adapter used when a real QMT endpoint is requested."""

    name = "qmt-unconfigured"

    def status(self) -> BrokerStatus:
        return BrokerStatus(
            adapter=self.name,
            connection="blocked",
            mode="HUMAN_CONFIRM",
            agent_pid=None,
            sdk_configured=False,
            network_enabled=False,
            real_order_enabled=False,
            kill_switch=True,
            last_error="真实 QMT SDK 未配置; Phase 11 仅提供隔离协议和 mock 实现",
        )

    def connect(self) -> BrokerStatus:
        return self.status()

    def get_quote(self, symbol: str) -> QuoteSnapshot:
        return QuoteSnapshot(
            symbol=symbol.strip().upper(),
            last_price=None,
            bid_price=None,
            ask_price=None,
            bid_quantity=None,
            ask_quantity=None,
            as_of="",
            quality="UNAVAILABLE",
            provenance={"adapter": self.name, "sdk_configured": False, "network": False},
            reason="真实 QMT SDK 未配置",
        )

    def require_unavailable(self) -> None:
        raise BrokerError("真实 QMT SDK 未配置, 当前只能使用 mock broker", code="QMT_NOT_CONFIGURED")
