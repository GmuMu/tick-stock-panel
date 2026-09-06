"""QMT Agent Core and its line-oriented process boundary.

The core has no QMT SDK dependency.  A future Windows worker can replace the
adapter behind this boundary without importing vendor objects into FastAPI.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from app.broker.protocol import BrokerAdapter, BrokerError, OrderRequest


class QmtAgentCore:
    """Command dispatcher that can be hosted in a separate process."""

    def __init__(self, adapter: BrokerAdapter) -> None:
        self.adapter = adapter

    def dispatch(self, command: dict[str, Any]) -> dict[str, Any]:
        action = str(command.get("action") or "").lower()
        if action == "connect":
            return {"ok": True, "result": self.adapter.connect().to_dict()}
        if action == "disconnect":
            return {"ok": True, "result": self.adapter.disconnect().to_dict()}
        if action == "status":
            return {"ok": True, "result": self.adapter.status().to_dict()}
        if action == "quote":
            return {"ok": True, "result": self.adapter.get_quote(str(command["symbol"])).to_dict()}
        if action == "orders":
            return {"ok": True, "result": [item.to_dict() for item in self.adapter.list_orders()]}
        if action == "fills":
            return {"ok": True, "result": [item.to_dict() for item in self.adapter.list_fills()]}
        if action == "account":
            return {"ok": True, "result": self.adapter.account_snapshot().to_dict()}
        if action == "submit_order":
            request = OrderRequest(**command["order"])
            return {"ok": True, "result": self.adapter.submit_order(request).to_dict()}
        if action == "cancel_order":
            return {"ok": True, "result": self.adapter.cancel_order(str(command["order_id"])).to_dict()}
        raise BrokerError(f"未知 Agent 命令: {action}", code="AGENT_COMMAND_INVALID")


def run_stdio_agent(core: QmtAgentCore) -> None:
    """Run a JSON-lines command loop for an external process boundary."""
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            result = core.dispatch(json.loads(line))
        except Exception as exc:
            result = {"ok": False, "error": str(exc), "code": getattr(exc, "code", "AGENT_ERROR")}
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def agent_metadata() -> dict[str, Any]:
    return {"pid": os.getpid(), "transport": "stdio-jsonl", "vendor_sdk_loaded": False}
