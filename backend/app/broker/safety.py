"""Fail-closed safety gates for the Broker/QMT boundary."""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.broker.protocol import BrokerSafetyError, ExecutionMode, utc_now


@dataclass
class SafetyState:
    kill_switch: bool = False
    mode: ExecutionMode = "HUMAN_CONFIRM"
    real_order_enabled: bool = False
    reason: str | None = None
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SafetyController:
    """Persisted kill switch and execution-mode policy.

    AUTO is intentionally rejected even if a caller attempts to enable it.
    LIVE_SHADOW can pass the policy but must still use a shadow/mock adapter.
    """

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "user_data" / "broker_safety.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._state = self._load()

    def _load(self) -> SafetyState:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            mode = raw.get("mode", "HUMAN_CONFIRM")
            # AUTO is never a recoverable persisted state in Phase 11.
            if mode not in {"HUMAN_CONFIRM", "LIVE_SHADOW"}:
                mode = "HUMAN_CONFIRM"
            return SafetyState(
                kill_switch=bool(raw.get("kill_switch", False)),
                mode=mode,
                real_order_enabled=False,
                reason=raw.get("reason"),
                updated_at=raw.get("updated_at") or utc_now(),
            )
        except (OSError, ValueError, TypeError):
            return SafetyState(updated_at=utc_now())

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self._state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def state(self) -> dict[str, Any]:
        with self._lock:
            return self._state.to_dict()

    def set_mode(self, mode: ExecutionMode) -> dict[str, Any]:
        if mode == "AUTO":
            raise BrokerSafetyError("AUTO 模式当前被安全策略禁用", code="AUTO_DISABLED")
        with self._lock:
            self._state.mode = mode
            self._state.real_order_enabled = False
            self._state.reason = None
            self._state.updated_at = utc_now()
            self._save()
            return self._state.to_dict()

    def trip(self, reason: str = "manual kill switch") -> dict[str, Any]:
        with self._lock:
            self._state.kill_switch = True
            self._state.real_order_enabled = False
            self._state.reason = reason
            self._state.updated_at = utc_now()
            self._save()
            return self._state.to_dict()

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self._state.kill_switch = False
            self._state.reason = None
            self._state.real_order_enabled = False
            self._state.updated_at = utc_now()
            self._save()
            return self._state.to_dict()

    def set_real_order_enabled(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            self._state.real_order_enabled = bool(enabled)
            self._state.updated_at = utc_now()
            self._save()
            return self._state.to_dict()

    def assert_can_trade(
        self,
        *,
        connected: bool,
        human_confirmed: bool,
        real_order_required: bool = False,
    ) -> None:
        with self._lock:
            if self._state.kill_switch:
                raise BrokerSafetyError(
                    f"Kill Switch 已触发: {self._state.reason or '未提供原因'}",
                    code="KILL_SWITCH_ACTIVE",
                )
            if not connected:
                raise BrokerSafetyError("Broker 未连接", code="BROKER_DISCONNECTED")
            if self._state.mode == "AUTO":
                raise BrokerSafetyError("AUTO 模式当前被安全策略禁用", code="AUTO_DISABLED")
            if self._state.mode == "HUMAN_CONFIRM" and not human_confirmed:
                raise BrokerSafetyError("HUMAN_CONFIRM 模式需要人工确认", code="HUMAN_CONFIRM_REQUIRED")
            if real_order_required and not self._state.real_order_enabled:
                raise BrokerSafetyError(
                    "真实下单尚未通过 Small Live 激活",
                    code="QMT_LIVE_DISABLED",
                )
