"""统一数据质量结果契约。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

QualityStatus = Literal["FRESH", "PARTIAL", "STALE", "MISSING", "INVALID"]


@dataclass(frozen=True)
class DataQuality:
    """一份可序列化的数据质量判定。"""

    dataset: str
    status: QualityStatus
    coverage_ratio: float | None
    expected_rows: int | None
    actual_rows: int | None
    observed_at: datetime | None
    age_seconds: float | None
    stale_after_seconds: float | None
    reason: str
    usable: bool

    @classmethod
    def from_counts(
        cls,
        dataset: str,
        *,
        expected_rows: int,
        actual_rows: int,
        observed_at: datetime | None = None,
        now: datetime | None = None,
        stale_after_seconds: float | None = None,
        partial_floor: float = 0.8,
    ) -> DataQuality:
        """按期望/实际行数和观测时效生成严格质量结果。"""
        if expected_rows < 0 or actual_rows < 0 or not 0 <= partial_floor <= 1:
            return cls._invalid(dataset, expected_rows, actual_rows, "invalid_counts")
        if stale_after_seconds is not None and stale_after_seconds < 0:
            return cls._invalid(dataset, expected_rows, actual_rows, "invalid_stale_window")
        age = cls._age_seconds(observed_at, now)
        if (
            age is not None
            and stale_after_seconds is not None
            and age > stale_after_seconds
        ):
            return cls(
                dataset, "STALE", None, expected_rows, actual_rows, observed_at, age,
                stale_after_seconds, "observation_stale", False,
            )
        if expected_rows == 0:
            return cls(
                dataset, "FRESH", 1.0, expected_rows, actual_rows, observed_at, age,
                stale_after_seconds, "not_required", True,
            )
        ratio = min(1.0, actual_rows / expected_rows)
        if actual_rows == 0:
            status: QualityStatus = "MISSING"
            reason = "no_rows"
        elif ratio < partial_floor:
            status = "PARTIAL"
            reason = "coverage_below_floor"
        elif ratio < 1.0:
            status = "PARTIAL"
            reason = "coverage_incomplete"
        else:
            status = "FRESH"
            reason = "complete"
        return cls(
            dataset, status, ratio, expected_rows, actual_rows, observed_at, age,
            stale_after_seconds, reason, status == "FRESH",
        )

    @classmethod
    def from_observation(
        cls,
        dataset: str,
        *,
        observed_at: datetime | None,
        now: datetime | None = None,
        stale_after_seconds: float,
        actual_rows: int | None = None,
        reason: str = "observed",
    ) -> DataQuality:
        """按最近一次成功观测生成 freshness 质量结果。"""
        if stale_after_seconds < 0:
            return cls._invalid(dataset, None, actual_rows, "invalid_stale_window")
        if observed_at is None:
            return cls(
                dataset, "MISSING", None, None, actual_rows, None, None,
                stale_after_seconds, "no_observation", False,
            )
        if actual_rows is not None and actual_rows < 0:
            return cls._invalid(dataset, None, actual_rows, "invalid_rows")
        age = cls._age_seconds(observed_at, now)
        if age is not None and age > stale_after_seconds:
            return cls(
                dataset, "STALE", None, None, actual_rows, observed_at, age,
                stale_after_seconds, "observation_stale", False,
            )
        return cls(
            dataset, "FRESH", None, None, actual_rows, observed_at, age,
            stale_after_seconds, reason, True,
        )

    def to_dict(self) -> dict[str, object | None]:
        """返回不含非 JSON 类型的稳定结构。"""
        return {
            "dataset": self.dataset,
            "status": self.status,
            "usable": self.usable,
            "fail_closed": not self.usable,
            "coverage_ratio": self.coverage_ratio,
            "expected_rows": self.expected_rows,
            "actual_rows": self.actual_rows,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "age_seconds": round(self.age_seconds, 3) if self.age_seconds is not None else None,
            "stale_after_seconds": self.stale_after_seconds,
            "reason": self.reason,
        }

    @staticmethod
    def _age_seconds(
        observed_at: datetime | None,
        now: datetime | None,
    ) -> float | None:
        if observed_at is None:
            return None
        current = now or datetime.now(observed_at.tzinfo)
        if observed_at.tzinfo is None and current.tzinfo is not None:
            current = current.replace(tzinfo=None)
        elif observed_at.tzinfo is not None and current.tzinfo is None:
            current = current.replace(tzinfo=observed_at.tzinfo)
        return max(0.0, (current - observed_at).total_seconds())

    @classmethod
    def _invalid(
        cls,
        dataset: str,
        expected_rows: int | None,
        actual_rows: int | None,
        reason: str,
    ) -> DataQuality:
        return cls(
            dataset, "INVALID", None, expected_rows, actual_rows, None, None,
            None, reason, False,
        )
