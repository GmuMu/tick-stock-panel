"""Versioned strategy metadata and execution provenance.

The contract is deliberately an adapter around the existing strategy engine.
It describes a strategy and its inputs/outputs without introducing a second
execution path.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

STRATEGY_CONTRACT_VERSION = "1.0"
DEFAULT_STRATEGY_VERSION = "1.0.0"
STRATEGY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
STRATEGY_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

STRATEGY_SOURCES = frozenset({"builtin", "custom", "ai", "composite"})
EXECUTION_BACKENDS = frozenset({
    "polars_expr",
    "matrix_native",
    "python_history_legacy",
    "composite",
    "minute_filter",
})
STRATEGY_LIFECYCLES = frozenset({
    "draft",
    "active",
    "disabled",
    "archived",
    "research",
})


@dataclass(frozen=True)
class StrategyContract:
    """Normalized, serializable strategy contract."""

    contract_version: str
    strategy_id: str
    strategy_version: str
    source: str
    execution_backend: str
    lifecycle: str
    asset_types: tuple[str, ...]
    timeframes: tuple[str, ...]
    required_features: tuple[str, ...] = ()
    entry_signals: tuple[str, ...] = ()
    exit_signals: tuple[str, ...] = ()
    lookback_days: int = 1
    warmup_bars: int = 1
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-friendly primitive containers for API and logs."""
        result = asdict(self)
        for key in (
            "asset_types",
            "timeframes",
            "required_features",
            "entry_signals",
            "exit_signals",
        ):
            result[key] = list(result[key])
        return result

    def meta_fields(self) -> dict[str, Any]:
        """Return the contract fields that belong in strategy META output."""
        return {
            "contract_version": self.contract_version,
            "version": self.strategy_version,
            "lifecycle": self.lifecycle,
            "provenance": dict(self.provenance),
            "lookback_days": self.lookback_days,
            "warmup_bars": self.warmup_bars,
        }


def _string_list(value: Any, field_name: str, *, required: bool = True) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or (required and not value):
        raise ValueError(f"META[{field_name!r}] must be a non-empty string list")
    values = tuple(dict.fromkeys(value))
    if any(not isinstance(item, str) or not item for item in values):
        raise ValueError(f"META[{field_name!r}] must be a non-empty string list")
    return values


def _non_negative_int(value: Any, field_name: str, *, minimum: int = 1) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"META[{field_name!r}] must be an integer") from exc
    if normalized < minimum:
        raise ValueError(f"META[{field_name!r}] must be >= {minimum}")
    return normalized


def normalize_contract(
    meta: Mapping[str, Any],
    *,
    source: str,
    execution_backend: str,
    required_features: Any = (),
    entry_signals: Any = (),
    exit_signals: Any = (),
    lookback_days: Any = 1,
    warmup_bars: Any = 1,
) -> tuple[dict[str, Any], StrategyContract]:
    """Validate and normalize a strategy META mapping.

    Unknown META fields are preserved so existing custom strategy extensions
    continue to work. Contract-owned fields are normalized and overwritten
    with canonical values.
    """
    normalized = dict(meta)
    strategy_id = normalized.get("id")
    if not isinstance(strategy_id, str) or not STRATEGY_ID_PATTERN.fullmatch(strategy_id):
        raise ValueError(
            "META['id'] must contain only letters, numbers, underscores, and hyphens"
        )
    if source not in STRATEGY_SOURCES:
        raise ValueError(f"unsupported strategy source {source!r}")
    if execution_backend not in EXECUTION_BACKENDS:
        raise ValueError(f"unsupported execution backend {execution_backend!r}")

    raw_version = normalized.get("version", DEFAULT_STRATEGY_VERSION)
    if not isinstance(raw_version, str) or not STRATEGY_VERSION_PATTERN.fullmatch(raw_version):
        raise ValueError(
            "META['version'] must use semantic version format MAJOR.MINOR.PATCH"
        )

    default_lifecycle = "research" if normalized.get("research_only") else "active"
    lifecycle = normalized.get("lifecycle", default_lifecycle)
    if lifecycle not in STRATEGY_LIFECYCLES:
        raise ValueError(
            f"META['lifecycle'] must be one of {sorted(STRATEGY_LIFECYCLES)}"
        )

    assets = _string_list(normalized.get("asset_types"), "asset_types")
    timeframes = _string_list(normalized.get("timeframes"), "timeframes")
    features = _string_list(
        list(required_features or ()),
        "required_features",
        required=False,
    )
    entries = _string_list(list(entry_signals or ()), "entry_signals", required=False)
    exits = _string_list(list(exit_signals or ()), "exit_signals", required=False)
    normalized_lookback = _non_negative_int(lookback_days, "lookback_days")
    normalized_warmup = _non_negative_int(warmup_bars, "warmup_bars")

    raw_provenance = normalized.get("provenance", {})
    if raw_provenance is None:
        raw_provenance = {}
    if not isinstance(raw_provenance, Mapping):
        raise ValueError("META['provenance'] must be a mapping")

    provenance = {
        **dict(raw_provenance),
        "contract_version": STRATEGY_CONTRACT_VERSION,
        "strategy_id": strategy_id,
        "strategy_version": raw_version,
        "source": source,
        "execution_backend": execution_backend,
        "lifecycle": lifecycle,
        "required_features": list(features),
    }
    contract = StrategyContract(
        contract_version=STRATEGY_CONTRACT_VERSION,
        strategy_id=strategy_id,
        strategy_version=raw_version,
        source=source,
        execution_backend=execution_backend,
        lifecycle=lifecycle,
        asset_types=assets,
        timeframes=timeframes,
        required_features=features,
        entry_signals=entries,
        exit_signals=exits,
        lookback_days=normalized_lookback,
        warmup_bars=normalized_warmup,
        provenance=provenance,
    )
    normalized.update(contract.meta_fields())
    normalized["asset_types"] = list(assets)
    normalized["timeframes"] = list(timeframes)
    normalized["required_features"] = list(features)
    normalized["entry_signals"] = list(entries)
    normalized["exit_signals"] = list(exits)
    return normalized, contract


def contract_for_strategy(strategy: Any) -> StrategyContract:
    """Return a contract for loaded or manually constructed StrategyDef objects."""
    contract = getattr(strategy, "contract", None)
    if isinstance(contract, StrategyContract):
        return contract

    meta = dict(getattr(strategy, "meta", {}) or {})
    required_features = set(getattr(strategy, "required_features", ()) or ())
    backend = str(getattr(strategy, "execution_backend", "polars_expr"))
    source = str(getattr(strategy, "source", "custom"))
    lookback_days = max(1, int(getattr(strategy, "lookback_days", 1) or 1))
    normalized, contract = normalize_contract(
        {
            **meta,
            "id": meta.get("id", "unknown"),
            "asset_types": meta.get("asset_types", ["stock"]),
            "timeframes": meta.get("timeframes", ["1d"]),
        },
        source=source,
        execution_backend=backend,
        required_features=required_features,
        entry_signals=getattr(strategy, "entry_signals", ()),
        exit_signals=getattr(strategy, "exit_signals", ()),
        lookback_days=lookback_days,
        warmup_bars=max(1, int(meta.get("warmup_bars", lookback_days) or lookback_days)),
    )
    del normalized
    return contract


def execution_provenance(strategy: Any, context: Any, as_of: Any) -> dict[str, Any]:
    """Build the immutable-at-the-call-site provenance for a StrategyResult."""
    contract = contract_for_strategy(strategy)
    return {
        **contract.provenance,
        "contract_version": contract.contract_version,
        "strategy_id": contract.strategy_id,
        "strategy_version": contract.strategy_version,
        "source": contract.source,
        "execution_backend": contract.execution_backend,
        "lifecycle": contract.lifecycle,
        "asset_type": str(context.asset_type),
        "timeframe": str(context.timeframe),
        "as_of": str(as_of),
        "input_features": list(contract.required_features),
        "lookback_days": contract.lookback_days,
        "warmup_bars": contract.warmup_bars,
    }
