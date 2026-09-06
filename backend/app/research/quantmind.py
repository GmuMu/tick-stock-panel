"""Local QuantMind-shaped adapter with no network or trading side effects."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from app.research.contract import ResearchArtifact


class QuantMindAdapter:
    """Read artifacts from a local handoff file.

    A future vendor connector must replace this class behind the same contract
    and remain outside the OMS/Broker import graph.
    """

    name = "quantmind"

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "user_data" / "research" / "quantmind.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def list_artifacts(self, limit: int = 100) -> list[ResearchArtifact]:
        if limit <= 0:
            return []
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return []
            except (OSError, ValueError, TypeError) as exc:
                raise ValueError("QuantMind research handoff 文件无效") from exc
        if not isinstance(raw, list):
            raise ValueError("QuantMind research handoff 必须是数组")
        return [ResearchArtifact.from_dict(item) for item in raw[-limit:]][::-1]

    def ingest(self, artifact: ResearchArtifact) -> ResearchArtifact:
        if artifact.provider != self.name:
            raise ValueError("Research artifact provider 与 QuantMind 不一致")
        with self._lock:
            items = [item.to_dict() for item in self.list_artifacts(limit=10000)]
            items = [item for item in items if item["artifact_id"] != artifact.artifact_id]
            items.append(artifact.to_dict())
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, self.path)
        return artifact
