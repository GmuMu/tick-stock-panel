"""Versioned metadata for the built-in indicator pipeline.

This module describes indicator contracts only.  It deliberately does not
contain calculation expressions; ``pipeline.py`` remains the single
implementation of indicator values.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

INDICATOR_SPEC_VERSION = "1.0.0"


@dataclass(frozen=True)
class IndicatorSpec:
    """Metadata contract for one pipeline output or internal intermediate."""

    name: str
    category: str
    version: str = INDICATOR_SPEC_VERSION
    dependencies: frozenset[str] = frozenset()
    input_columns: frozenset[str] = frozenset()
    windows: tuple[int, ...] = ()
    min_periods: int | None = None
    internal: bool = False
    description: str = ""

    @property
    def warmup_bars(self) -> int:
        """Conservative warm-up requirement derived from declared windows."""
        if self.min_periods is not None:
            return max(self.min_periods, max(self.windows, default=1))
        return max(self.windows, default=1)


def _spec(
    name: str,
    category: str,
    *,
    dependencies: set[str] | frozenset[str] = frozenset(),
    input_columns: set[str] | frozenset[str] = frozenset(),
    windows: tuple[int, ...] = (),
    min_periods: int | None = None,
    internal: bool = False,
    description: str = "",
) -> IndicatorSpec:
    return IndicatorSpec(
        name=name,
        category=category,
        dependencies=frozenset(dependencies),
        input_columns=frozenset(input_columns),
        windows=tuple(int(window) for window in windows),
        min_periods=min_periods,
        internal=internal,
        description=description,
    )


_SPECS = (
    _spec("prev_close", "basic", input_columns={"close"}, windows=(1,)),
    _spec("change_pct", "basic", input_columns={"close"}, windows=(1,)),
    _spec("change_amount", "basic", input_columns={"close"}, windows=(1,)),
    _spec("amplitude", "basic", input_columns={"high", "low", "close"}, windows=(1,)),
    _spec("ma5", "ma", input_columns={"close"}, windows=(5,)),
    _spec("ma10", "ma", input_columns={"close"}, windows=(10,)),
    _spec("ma20", "ma", input_columns={"close"}, windows=(20,)),
    _spec("ma30", "ma", input_columns={"close"}, windows=(30,)),
    _spec("ma60", "ma", input_columns={"close"}, windows=(60,)),
    _spec("ema5", "ema", input_columns={"close"}, windows=(5,)),
    _spec("ema10", "ema", input_columns={"close"}, windows=(10,)),
    _spec("ema20", "ema", input_columns={"close"}, windows=(20,)),
    _spec("ema30", "ema", input_columns={"close"}, windows=(30,)),
    _spec("ema60", "ema", input_columns={"close"}, windows=(60,)),
    _spec(
        "_ema12",
        "ema",
        input_columns={"close"},
        windows=(12,),
        internal=True,
    ),
    _spec(
        "_ema26",
        "ema",
        input_columns={"close"},
        windows=(26,),
        internal=True,
    ),
    _spec(
        "_boll_std",
        "boll",
        input_columns={"close"},
        windows=(20,),
        internal=True,
    ),
    _spec(
        "_kdj_ln",
        "kdj",
        input_columns={"low"},
        windows=(9,),
        internal=True,
    ),
    _spec(
        "_kdj_hn",
        "kdj",
        input_columns={"high"},
        windows=(9,),
        internal=True,
    ),
    _spec(
        "_tr",
        "atr",
        dependencies={"prev_close"},
        input_columns={"high", "low", "close"},
        windows=(1,),
        internal=True,
    ),
    _spec(
        "_vol_ma5",
        "volume",
        input_columns={"volume"},
        windows=(5,),
        internal=True,
    ),
    _spec(
        "_vol_ma5_prev",
        "volume",
        input_columns={"volume"},
        windows=(5, 1),
        internal=True,
    ),
    _spec("vol_ma5", "volume", input_columns={"volume"}, windows=(5,)),
    _spec("vol_ma10", "volume", input_columns={"volume"}, windows=(10,)),
    _spec(
        "vol_ratio_5d",
        "volume",
        dependencies={"_vol_ma5_prev"},
        input_columns={"volume"},
        windows=(5, 1),
    ),
    _spec("high_60d", "extremes", input_columns={"close"}, windows=(60,)),
    _spec("low_60d", "extremes", input_columns={"close"}, windows=(60,)),
    _spec(
        "macd_dif",
        "macd",
        dependencies={"_ema12", "_ema26"},
        input_columns={"close"},
        windows=(12, 26),
    ),
    _spec(
        "macd_dea",
        "macd",
        dependencies={"macd_dif"},
        input_columns={"close"},
        windows=(9, 12, 26),
    ),
    _spec(
        "macd_hist",
        "macd",
        dependencies={"macd_dif", "macd_dea"},
        input_columns={"close"},
        windows=(9, 12, 26),
    ),
    _spec(
        "boll_upper",
        "boll",
        dependencies={"ma20", "_boll_std"},
        input_columns={"close"},
        windows=(20,),
    ),
    _spec(
        "boll_lower",
        "boll",
        dependencies={"ma20", "_boll_std"},
        input_columns={"close"},
        windows=(20,),
    ),
    _spec(
        "kdj_k",
        "kdj",
        dependencies={"_kdj_ln", "_kdj_hn"},
        input_columns={"close", "high", "low"},
        windows=(9,),
    ),
    _spec("kdj_d", "kdj", dependencies={"kdj_k"}, windows=(9,)),
    _spec("kdj_j", "kdj", dependencies={"kdj_k", "kdj_d"}, windows=(9,)),
    _spec(
        "atr_14",
        "atr",
        dependencies={"_tr"},
        input_columns={"high", "low", "close"},
        windows=(14,),
    ),
    _spec(
        "momentum_5d",
        "momentum",
        input_columns={"close"},
        windows=(5,),
    ),
    _spec(
        "momentum_10d",
        "momentum",
        input_columns={"close"},
        windows=(10,),
    ),
    _spec(
        "momentum_20d",
        "momentum",
        input_columns={"close"},
        windows=(20,),
    ),
    _spec(
        "momentum_30d",
        "momentum",
        input_columns={"close"},
        windows=(30,),
    ),
    _spec(
        "momentum_60d",
        "momentum",
        input_columns={"close"},
        windows=(60,),
    ),
    _spec(
        "_daily_pct",
        "volatility",
        input_columns={"close"},
        windows=(1,),
        internal=True,
    ),
    _spec(
        "annual_vol_20d",
        "volatility",
        dependencies={"_daily_pct"},
        input_columns={"close"},
        windows=(20,),
    ),
    _spec(
        "_delta",
        "rsi",
        input_columns={"close"},
        windows=(1,),
        internal=True,
    ),
    _spec("_gain", "rsi", dependencies={"_delta"}, windows=(1,), internal=True),
    _spec("_loss", "rsi", dependencies={"_delta"}, windows=(1,), internal=True),
    _spec(
        "rsi_6",
        "rsi",
        dependencies={"_delta", "_gain", "_loss"},
        input_columns={"close"},
        windows=(6,),
    ),
    _spec(
        "rsi_14",
        "rsi",
        dependencies={"_delta", "_gain", "_loss"},
        input_columns={"close"},
        windows=(14,),
    ),
    _spec(
        "rsi_24",
        "rsi",
        dependencies={"_delta", "_gain", "_loss"},
        input_columns={"close"},
        windows=(24,),
    ),
)


def _validate_specs(specs: tuple[IndicatorSpec, ...]) -> dict[str, IndicatorSpec]:
    by_name = {spec.name: spec for spec in specs}
    if len(by_name) != len(specs):
        raise ValueError("indicator spec names must be unique")
    for spec in specs:
        if spec.version != INDICATOR_SPEC_VERSION:
            raise ValueError(f"{spec.name} uses an unsupported indicator spec version")
        if any(window <= 0 for window in spec.windows):
            raise ValueError(f"{spec.name} windows must be positive")
        if spec.min_periods is not None and spec.min_periods <= 0:
            raise ValueError(f"{spec.name} min_periods must be positive")
        unknown = spec.dependencies - by_name.keys()
        # Dependencies may also be raw input columns, which are documented in
        # input_columns and do not need an IndicatorSpec entry.
        unknown -= spec.input_columns
        if unknown:
            raise ValueError(f"{spec.name} has unknown indicator dependencies: {sorted(unknown)}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ValueError(f"indicator spec dependency cycle at {name}")
        if name in visited:
            return
        visiting.add(name)
        for dependency in by_name[name].dependencies:
            if dependency in by_name:
                visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for name in by_name:
        visit(name)
    return by_name


INDICATOR_SPECS: Mapping[str, IndicatorSpec] = MappingProxyType(_validate_specs(_SPECS))
INDICATOR_DEPENDENCIES: Mapping[str, frozenset[str]] = MappingProxyType({
    name: spec.dependencies
    for name, spec in INDICATOR_SPECS.items()
    if spec.dependencies
})
ALL_INDICATOR_COLUMNS = frozenset(INDICATOR_SPECS)
INDICATOR_COLUMNS = frozenset(
    name for name, spec in INDICATOR_SPECS.items() if not spec.internal
)


def resolve_needed(needed: set[str] | None) -> set[str]:
    """Expand requested outputs to their transitive indicator dependencies."""
    if needed is None:
        return set(ALL_INDICATOR_COLUMNS)

    want = set(needed)
    changed = True
    while changed:
        changed = False
        for target in tuple(want):
            spec = INDICATOR_SPECS.get(target)
            if spec is None:
                continue
            dependencies = spec.dependencies - spec.input_columns
            if not dependencies <= want:
                want.update(dependencies)
                changed = True
    return want


def get_indicator_spec(name: str) -> IndicatorSpec:
    """Return one immutable spec or raise a clear error for unknown names."""
    try:
        return INDICATOR_SPECS[name]
    except KeyError as exc:
        raise KeyError(f"unknown indicator spec: {name}") from exc


def get_indicator_specs(*, include_internal: bool = True) -> tuple[IndicatorSpec, ...]:
    """Return specs in stable declaration order for APIs and documentation."""
    return tuple(
        spec for spec in _SPECS
        if include_internal or not spec.internal
    )
