"""Atomic local persistence for daily strategy candidate seeds."""
from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.strategy.candidates import StrategyCandidateBatch, jsonable_batch

_lock = threading.RLock()
_FILENAME = "eod_seeds.json"
_MAX_SEEDS = 500


class EODSeedStoreError(RuntimeError):
    pass


class EODSeedStore:
    def __init__(self, data_dir: Path | str) -> None:
        self.path = Path(data_dir) / "user_data" / _FILENAME

    def list(self, *, strategy_id: str | None = None, as_of: str | None = None) -> list[dict[str, Any]]:
        with _lock:
            values = self._load()
        if strategy_id is not None:
            values = [item for item in values if item.get("strategy_id") == strategy_id]
        if as_of is not None:
            values = [item for item in values if item.get("as_of") == as_of]
        return values

    def latest(self, strategy_id: str) -> dict[str, Any] | None:
        values = self.list(strategy_id=strategy_id)
        return values[0] if values else None

    def put(self, batch: StrategyCandidateBatch) -> dict[str, Any]:
        payload = jsonable_batch(batch)
        now = datetime.now(UTC).isoformat()
        item = {
            **payload,
            "created_at": now,
            "updated_at": now,
        }
        with _lock:
            values = self._load()
            existing = next(
                (value for value in values if value.get("seed_id") == batch.seed_id),
                None,
            )
            if existing is not None:
                if self._stable_payload(existing) != self._stable_payload(item):
                    raise EODSeedStoreError("相同 seed_id 的策略种子内容冲突")
                return existing
            values.insert(0, item)
            self._write(values[:_MAX_SEEDS])
        return item

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise EODSeedStoreError("EOD seed 文件损坏或无法读取") from exc
        if not isinstance(raw, list):
            raise EODSeedStoreError("EOD seed 文件格式无效")
        return [item for item in raw if isinstance(item, dict) and item.get("seed_id")]

    def _write(self, values: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        try:
            temporary.write_text(
                json.dumps(values, ensure_ascii=False, indent=2, allow_nan=False),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except (OSError, TypeError, ValueError) as exc:
            temporary.unlink(missing_ok=True)
            raise EODSeedStoreError("EOD seed 保存失败") from exc

    @staticmethod
    def _stable_payload(value: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value.get(key)
            for key in (
                "model_version",
                "strategy_id",
                "as_of",
                "seed_id",
                "candidates",
                "provenance",
                "data_quality",
            )
        }
