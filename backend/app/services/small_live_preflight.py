"""Fail-closed technical preflight for a future Small Live review.

This service only inspects normalized broker snapshots. It never enables real
orders, imports a vendor SDK, or submits an order.
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

from app.broker.protocol import utc_now


class SmallLivePreflightService:
    """Evaluate technical readiness without authorizing live trading."""

    def __init__(self, runtime: Any, data_dir: Path | None = None) -> None:
        self.runtime = runtime
        root = Path(data_dir or runtime.data_dir)
        self.path = root / "user_data" / "small_live_preflights.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def run(self, symbol: str) -> dict[str, Any]:
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("预检标的不能为空")

        checks: list[dict[str, Any]] = []
        blocking: list[dict[str, str]] = []

        status = self._read_status(checks, blocking)
        self._check_qmt_runtime(status, checks, blocking)
        self._check_agent(status, checks, blocking)
        self._check_quote(normalized, checks, blocking)
        self._check_account(checks, blocking)
        self._check_reconcile(checks, blocking)
        self._check_safety(status, checks, blocking)

        manual_review = [
            {
                "code": "LIVE_APPROVAL_REQUIRED",
                "detail": "需要独立的实盘审批记录和明确的批准人。",
            },
            {
                "code": "SMALL_LIVE_LIMITS_REQUIRED",
                "detail": "需要发布前确认单笔、单日、持仓和可交易标的限额。",
            },
            {
                "code": "RELEASE_RUNBOOK_REQUIRED",
                "detail": "需要按 Small Live runbook 完成发布、回滚和应急演练。",
            },
            {
                "code": "EMERGENCY_PROCEDURE_REQUIRED",
                "detail": "需要确认 Kill Switch、断连、异常成交和人工接管流程。",
            },
        ]
        result = {
            "id": f"small_live_preflight_{uuid.uuid4().hex[:12]}",
            "symbol": normalized,
            "status": "READY_FOR_REVIEW" if not blocking else "BLOCKED",
            # A passing preflight is not an authorization to activate a real
            # account.
            "activation_allowed": False,
            "real_order_enabled": False,
            "checks": checks,
            "blocking_reasons": blocking,
            "manual_review": manual_review,
            "created_at": utc_now(),
            "contract_version": "1.0",
        }
        self._append(result)
        return result

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []
        rows: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                rows.append(json.loads(line))
            except (TypeError, ValueError):
                continue
        return list(reversed(rows))

    def _read_status(
        self,
        checks: list[dict[str, Any]],
        blocking: list[dict[str, str]],
    ) -> dict[str, Any]:
        try:
            status = self.runtime.status()
        except Exception as exc:
            self._blocked(
                checks,
                blocking,
                "BROKER_STATUS_UNAVAILABLE",
                f"无法读取 Broker 状态: {type(exc).__name__}",
            )
            return {}
        self._passed(checks, "broker_status", "Broker 状态可读取")
        return status

    def _check_qmt_runtime(
        self,
        status: dict[str, Any],
        checks: list[dict[str, Any]],
        blocking: list[dict[str, str]],
    ) -> None:
        if status.get("adapter") != "qmt":
            self._blocked(checks, blocking, "QMT_ADAPTER_NOT_ACTIVE", "当前未选择 QMT 适配器")
        elif status.get("connection") != "connected":
            self._blocked(checks, blocking, "QMT_NOT_CONNECTED", "QMT Agent 未连接")
        else:
            self._passed(checks, "qmt_connection", "QMT 适配器已连接")

        agent = status.get("agent") or {}
        if not status.get("sdk_configured") or not agent.get("vendor_sdk_loaded"):
            self._blocked(
                checks,
                blocking,
                "QMT_SDK_UNAVAILABLE",
                "真实 QMT SDK 未配置或未由独立 Agent 加载",
            )
        else:
            self._passed(checks, "qmt_sdk", "QMT SDK 已由 Agent 加载")

        if status.get("network_enabled") is not True:
            self._blocked(checks, blocking, "QMT_NETWORK_UNAVAILABLE", "真实行情网络通道未启用")
        else:
            self._passed(checks, "qmt_network", "QMT 网络通道已启用")

        if status.get("agent_order_enabled") is not True:
            self._blocked(
                checks,
                blocking,
                "QMT_AGENT_ORDERS_DISABLED",
                "QMT Agent 下单能力未显式开启",
            )
        else:
            self._passed(checks, "qmt_agent_orders", "QMT Agent 下单能力已配置")

        if status.get("live_order_configured") is not True:
            self._blocked(
                checks,
                blocking,
                "QMT_LIVE_CONFIG_DISABLED",
                "应用侧 QMT_LIVE_ORDER_ENABLED 未开启",
            )
        else:
            self._passed(checks, "qmt_live_config", "应用侧实盘配置开关已开启")

    def _check_agent(
        self,
        status: dict[str, Any],
        checks: list[dict[str, Any]],
        blocking: list[dict[str, str]],
    ) -> None:
        agent = status.get("agent") or {}
        if (
            agent.get("isolated") is not True
            or agent.get("transport") not in {"stdio-jsonl", "external-stdio-jsonl"}
        ):
            self._blocked(
                checks,
                blocking,
                "AGENT_ISOLATION_REQUIRED",
                "QMT Agent 必须以独立进程和 JSONL 边界运行",
            )
        else:
            self._passed(checks, "agent_isolation", "Agent 进程隔离边界满足")

    def _check_quote(
        self,
        symbol: str,
        checks: list[dict[str, Any]],
        blocking: list[dict[str, str]],
    ) -> None:
        try:
            quote = self.runtime.quote(symbol)
        except Exception as exc:
            self._blocked(
                checks,
                blocking,
                "QUOTE_SNAPSHOT_UNAVAILABLE",
                f"无法读取行情快照: {type(exc).__name__}",
            )
            return
        if quote.get("quality") != "FRESH":
            self._blocked(checks, blocking, "QUOTE_NOT_FRESH", "Small Live 需要 FRESH 行情快照")
        else:
            self._passed(checks, "quote_quality", "行情快照为 FRESH")

    def _check_account(
        self,
        checks: list[dict[str, Any]],
        blocking: list[dict[str, str]],
    ) -> None:
        try:
            account = self.runtime.account()
        except Exception as exc:
            self._blocked(
                checks,
                blocking,
                "ACCOUNT_SNAPSHOT_UNAVAILABLE",
                f"无法读取账户快照: {type(exc).__name__}",
            )
            return
        if account.get("quality") != "FRESH" or not account.get("account_id"):
            self._blocked(
                checks,
                blocking,
                "ACCOUNT_SNAPSHOT_UNAVAILABLE",
                "账户快照不可用或不是 FRESH",
            )
        else:
            self._passed(checks, "account_quality", "账户快照为 FRESH")

    def _check_reconcile(
        self,
        checks: list[dict[str, Any]],
        blocking: list[dict[str, str]],
    ) -> None:
        try:
            rows = self.runtime.list_reconciliations(limit=1)
        except Exception as exc:
            self._blocked(
                checks,
                blocking,
                "RECONCILIATION_UNAVAILABLE",
                f"无法读取最近对账结果: {type(exc).__name__}",
            )
            return
        report = rows[0].get("report", {}) if rows else {}
        if report.get("status") != "matched":
            self._blocked(
                checks,
                blocking,
                "RECONCILIATION_REQUIRED",
                "必须存在最近一次 matched 对账结果",
            )
        else:
            self._passed(checks, "reconciliation", "最近一次对账结果为 matched")

    def _check_safety(
        self,
        status: dict[str, Any],
        checks: list[dict[str, Any]],
        blocking: list[dict[str, str]],
    ) -> None:
        if status.get("kill_switch"):
            self._blocked(checks, blocking, "KILL_SWITCH_ACTIVE", "Kill Switch 当前已触发")
        elif status.get("mode") != "HUMAN_CONFIRM":
            self._blocked(
                checks,
                blocking,
                "HUMAN_CONFIRM_REQUIRED",
                "Small Live 评审必须保持 HUMAN_CONFIRM 模式",
            )
        elif status.get("real_order_enabled") is not False:
            self._blocked(
                checks,
                blocking,
                "REAL_ORDER_GUARD_INVALID",
                "预检阶段真实下单开关必须保持关闭",
            )
        else:
            self._passed(checks, "safety_gates", "Kill Switch 未触发且真实下单保持关闭")

    @staticmethod
    def _passed(checks: list[dict[str, Any]], code: str, detail: str) -> None:
        checks.append({"code": code, "status": "passed", "detail": detail})

    @staticmethod
    def _blocked(
        checks: list[dict[str, Any]],
        blocking: list[dict[str, str]],
        code: str,
        detail: str,
    ) -> None:
        checks.append({"code": code, "status": "blocked", "detail": detail})
        blocking.append({"code": code, "detail": detail})

    def _append(self, result: dict[str, Any]) -> None:
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
