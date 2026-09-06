"""No-real-side-effect LIVE_SHADOW acceptance loop."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.broker.protocol import BrokerError, OrderRequest, utc_now

if TYPE_CHECKING:
    from app.broker.runtime import BrokerRuntime


class LiveShadowRunner:
    """Exercise quote -> trade adapter -> optional fill -> reconcile on mock."""

    def run(
        self,
        runtime: BrokerRuntime,
        request: OrderRequest,
        *,
        simulate_fill: bool = False,
    ) -> dict[str, Any]:
        status = runtime.status()
        if status["adapter"] != "mock" or status["mode"] != "LIVE_SHADOW":
            raise BrokerError("LIVE_SHADOW 必须使用 mock 适配器和 LIVE_SHADOW 模式", code="LIVE_SHADOW_NOT_READY")
        if status["connection"] != "connected":
            raise BrokerError("LIVE_SHADOW Broker 尚未连接", code="BROKER_DISCONNECTED")
        quote = runtime.quote(request.symbol)
        if quote.get("quality") != "FRESH":
            raise BrokerError("LIVE_SHADOW 缺少 FRESH 行情", code="LIVE_SHADOW_QUOTE_UNAVAILABLE")

        stages: list[dict[str, Any]] = [
            {"name": "preflight", "status": "passed", "detail": "mock adapter, isolated agent, no network"},
            {"name": "quote", "status": "passed", "quote": quote},
        ]
        order = runtime.submit(request)
        stages.append({"name": "submit", "status": "passed", "order_id": order["id"]})
        fill = None
        if simulate_fill:
            fill = runtime.simulate_fill(order["id"], request.quantity, request.limit_price)
            stages.append({"name": "fill", "status": "passed", "fill_id": fill["id"]})
        reconciliation = runtime.reconcile_snapshot()
        stages.append({"name": "reconcile", "status": reconciliation["status"], "report_id": reconciliation.get("id")})
        return {
            "id": f"shadow_{utc_now().replace(':', '').replace('+', '-')}",
            "status": "passed" if reconciliation["status"] == "matched" else "mismatched",
            "stages": stages,
            "order": order,
            "fill": fill,
            "reconciliation": reconciliation,
            "real_order_submitted": False,
            "network_enabled": False,
        }
