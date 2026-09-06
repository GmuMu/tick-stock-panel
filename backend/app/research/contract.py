"""Vendor-neutral research artifact contract."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

RESEARCH_CONTRACT_VERSION = "1.0"


@dataclass(frozen=True)
class ResearchArtifact:
    artifact_id: str
    provider: str
    symbol: str
    as_of: str
    thesis: str
    score: float | None = None
    features: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    contract_version: str = RESEARCH_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        result = self._canonical_dict()
        result["fingerprint"] = self.fingerprint()
        return result

    def _canonical_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ResearchArtifact:
        required = ("artifact_id", "provider", "symbol", "as_of", "thesis")
        if any(not str(value.get(key) or "").strip() for key in required):
            raise ValueError("Research artifact 缺少必填字段")
        score = value.get("score")
        if score is not None:
            score = float(score)
            if score != score or score in (float("inf"), float("-inf")):
                raise ValueError("Research artifact score 必须是有限数值")
        artifact = cls(
            artifact_id=str(value["artifact_id"]).strip(),
            provider=str(value["provider"]).strip().lower(),
            symbol=str(value["symbol"]).strip().upper(),
            as_of=str(value["as_of"]).strip(),
            thesis=str(value["thesis"]).strip(),
            score=score,
            features=dict(value.get("features") or {}),
            payload=dict(value.get("payload") or {}),
            provenance=dict(value.get("provenance") or {}),
            contract_version=str(value.get("contract_version") or RESEARCH_CONTRACT_VERSION),
        )
        json.dumps(artifact.to_dict(), ensure_ascii=False, allow_nan=False)
        return artifact

    def fingerprint(self) -> str:
        raw = json.dumps(
            self._canonical_dict(), ensure_ascii=False, sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:24]


class ResearchAdapter(Protocol):
    name: str

    def list_artifacts(self, limit: int = 100) -> list[ResearchArtifact]: ...
