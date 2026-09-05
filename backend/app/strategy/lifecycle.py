"""Persistent strategy lifecycle and source revision contract."""
from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.strategy.contract import STRATEGY_LIFECYCLES

_lock = threading.RLock()
_FILENAME = "strategy_lifecycle.json"
_REVISION_DIR = "strategy_revisions"

_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"active", "disabled", "archived"}),
    "active": frozenset({"disabled", "archived"}),
    "disabled": frozenset({"active", "archived"}),
    "archived": frozenset({"draft", "active"}),
    "research": frozenset({"active", "disabled", "archived"}),
}


class StrategyLifecycleError(ValueError):
    pass


class StrategyLifecycleStore:
    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "user_data" / _FILENAME
        self.revision_dir = self.data_dir / "user_data" / _REVISION_DIR

    def get(self, strategy_id: str, default: str = "active") -> dict[str, Any]:
        with _lock:
            values = self._load()
        item = values.get(strategy_id)
        if item is not None:
            return dict(item)
        if default not in STRATEGY_LIFECYCLES:
            default = "active"
        return {
            "strategy_id": strategy_id,
            "state": default,
            "revision": 0,
            "updated_at": None,
            "reason": "default",
            "history": [],
        }

    def register(self, strategy_id: str, state: str = "active") -> dict[str, Any]:
        if state not in STRATEGY_LIFECYCLES:
            raise StrategyLifecycleError(f"不支持的策略生命周期: {state}")
        with _lock:
            values = self._load()
            if strategy_id in values:
                return dict(values[strategy_id])
            item = self._new_item(strategy_id, state)
            values[strategy_id] = item
            self._write(values)
            return dict(item)

    def transition(
        self,
        strategy_id: str,
        state: str,
        *,
        current_state: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        if state not in STRATEGY_LIFECYCLES:
            raise StrategyLifecycleError(f"不支持的策略生命周期: {state}")
        with _lock:
            values = self._load()
            item = values.get(strategy_id) or self._new_item(strategy_id, "active")
            previous = str(item.get("state", "active"))
            if current_state is not None and previous != current_state:
                raise StrategyLifecycleError(
                    f"策略状态已变化: 期望 {current_state}, 实际 {previous}"
                )
            if state != previous and state not in _TRANSITIONS.get(previous, frozenset()):
                raise StrategyLifecycleError(f"策略不允许从 {previous} 迁移到 {state}")
            if state == previous:
                return dict(item)
            now = datetime.now(UTC).isoformat()
            history = list(item.get("history") or [])
            history.append({"from": previous, "to": state, "at": now, "reason": reason})
            item = {
                **item,
                "state": state,
                "revision": int(item.get("revision", 0)) + 1,
                "updated_at": now,
                "reason": reason,
                "history": history[-20:],
            }
            values[strategy_id] = item
            self._write(values)
            return dict(item)

    def snapshot_source(self, strategy_id: str, code: str, *, version: str = "1.0.0") -> dict[str, Any]:
        if not isinstance(code, str):
            raise StrategyLifecycleError("策略源码必须是文本")
        with _lock:
            now = datetime.now(UTC).isoformat()
            item = self.get(strategy_id)
            revision = int(item.get("source_revision", 0)) + 1
            directory = self.revision_dir / strategy_id
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{revision}.py"
            path.write_text(code, encoding="utf-8")
            meta_path = directory / f"{revision}.json"
            meta_path.write_text(
                json.dumps(
                    {"strategy_id": strategy_id, "revision": revision, "version": version, "created_at": now},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            values = self._load()
            item = {
                **item,
                "source_revision": revision,
                "updated_at": now,
            }
            values[strategy_id] = item
            self._write(values)
            return {"strategy_id": strategy_id, "revision": revision, "version": version, "created_at": now}

    def read_source_revision(self, strategy_id: str, revision: int) -> str:
        if revision < 1:
            raise StrategyLifecycleError("源码修订号必须大于 0")
        path = self.revision_dir / strategy_id / f"{revision}.py"
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StrategyLifecycleError("找不到策略源码修订") from exc

    def list_source_revisions(self, strategy_id: str) -> list[dict[str, Any]]:
        directory = self.revision_dir / strategy_id
        result: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json"), key=lambda item: item.name, reverse=True):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                result.append(value)
        return result

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StrategyLifecycleError("策略生命周期文件损坏或无法读取") from exc
        return raw if isinstance(raw, dict) else {}

    def _write(self, values: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        try:
            temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise StrategyLifecycleError("策略生命周期保存失败") from exc

    @staticmethod
    def _new_item(strategy_id: str, state: str) -> dict[str, Any]:
        return {
            "strategy_id": strategy_id,
            "state": state,
            "revision": 0,
            "source_revision": 0,
            "updated_at": None,
            "reason": "default",
            "history": [],
        }
