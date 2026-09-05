"""Versioned contracts shared by every backtest entry point.

The execution engines intentionally keep their existing matching semantics.  This
module only describes what was requested, what data was actually available, and
why a run was accepted or rejected so that results remain auditable and portable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal

BACKTEST_DATA_CONTRACT_VERSION = "1.0"
BACKTEST_VALIDATION_CONTRACT_VERSION = "1.0"
BACKTEST_PROVENANCE_VERSION = "1.0"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class BacktestDataCoverage:
    """Serializable proof of the data window used by a backtest."""

    contract_version: str = BACKTEST_DATA_CONTRACT_VERSION
    asset_type: str = "stock"
    requested_start: str | None = None
    requested_end: str | None = None
    load_start: str | None = None
    load_end: str | None = None
    warmup_start: str | None = None
    simulation_start: str | None = None
    simulation_end: str | None = None
    forward_end: str | None = None
    actual_start: str | None = None
    actual_end: str | None = None
    symbol_count: int = 0
    row_count: int = 0
    complete: bool = False
    generation: str | None = None
    source: str | None = None
    storage_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BacktestValidation:
    """A stable, machine-readable validation outcome."""

    contract_version: str = BACKTEST_VALIDATION_CONTRACT_VERSION
    status: Literal["accepted", "rejected", "partial"] = "accepted"
    code: str = "ok"
    message: str = ""
    field: str | None = None
    requested: Any = None
    available: Any = None
    severity: Literal["info", "warning", "error"] = "info"
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BacktestProvenance:
    """Complete lineage for a result, including rejected runs."""

    contract_version: str = BACKTEST_PROVENANCE_VERSION
    run_id: str = ""
    engine: str = ""
    asset_type: str = "stock"
    data_generation: str | None = None
    data_coverage: dict[str, Any] = field(default_factory=dict)
    data_source: str | None = None
    storage_path: str | None = None
    indicator_version: str | None = None
    strategy_id: str | None = None
    strategy_version: str | None = None
    strategy_revision: int | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    overrides: dict[str, Any] = field(default_factory=dict)
    market_rules_version: str | None = None
    execution_config: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_ms: float | None = None
    worker: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def accepted_validation(message: str = "回测数据覆盖校验通过") -> BacktestValidation:
    return BacktestValidation(message=message)


def rejected_validation(
    code: str,
    message: str,
    *,
    field: str | None = None,
    requested: Any = None,
    available: Any = None,
    retryable: bool = False,
) -> BacktestValidation:
    return BacktestValidation(
        status="rejected",
        code=code,
        message=message,
        field=field,
        requested=requested,
        available=available,
        severity="error",
        retryable=retryable,
    )


def coverage_from_labels(
    labels: Any,
    *,
    asset_type: str,
    requested_start: date,
    requested_end: date,
    load_start: date,
    load_end: date,
    simulation_end: date,
    warmup_start: date | None = None,
    forward_end: date | None = None,
    symbol_count: int = 0,
    row_count: int = 0,
    generation: str | None = None,
    source: str | None = None,
    storage_path: str | None = None,
) -> BacktestDataCoverage:
    values = sorted({_text(value)[:10] for value in labels if _text(value)})
    actual_start = values[0] if values else None
    actual_end = values[-1] if values else None
    formal_start = requested_start.isoformat()
    formal_end = requested_end.isoformat()
    required_start = (warmup_start or load_start).isoformat()
    required_end = (forward_end or simulation_end).isoformat()
    complete = bool(values) and actual_start <= required_start and actual_end >= required_end
    return BacktestDataCoverage(
        asset_type=asset_type,
        requested_start=formal_start,
        requested_end=formal_end,
        load_start=load_start.isoformat(),
        load_end=load_end.isoformat(),
        warmup_start=(warmup_start or load_start).isoformat(),
        simulation_start=formal_start,
        simulation_end=simulation_end.isoformat(),
        forward_end=(forward_end or simulation_end).isoformat(),
        actual_start=actual_start,
        actual_end=actual_end,
        symbol_count=int(symbol_count),
        row_count=int(row_count),
        complete=complete,
        generation=generation,
        source=source,
        storage_path=storage_path,
    )


def coverage_from_panel(
    panel: Any,
    **kwargs: Any,
) -> BacktestDataCoverage:
    labels = panel.get_column("date").to_list() if "date" in panel.columns else []
    symbol_count = panel["symbol"].n_unique() if "symbol" in panel.columns else 0
    return coverage_from_labels(
        labels,
        symbol_count=symbol_count,
        row_count=len(panel),
        **kwargs,
    )


def coverage_from_matrix(matrix: Any, **kwargs: Any) -> BacktestDataCoverage:
    return coverage_from_labels(
        matrix.timestamp_labels,
        symbol_count=len(matrix.symbols),
        row_count=int(matrix.close.size),
        source=kwargs.pop("source", "enriched_parquet"),
        **kwargs,
    )
