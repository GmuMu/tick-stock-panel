"""EOD strategy runner built on the existing screener and strategy engine."""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from app.data_quality import DataQuality
from app.services.eod_seeds import EODSeedStore
from app.services.screener import ScreenerService
from app.strategy.candidates import batch_from_result


class EODRunnerError(RuntimeError):
    pass


def run_eod_seeds(
    repo: Any,
    engine: Any,
    data_dir: Path | str,
    *,
    as_of: date | None = None,
    asset_type: str = "stock",
    timeframe: str = "1d",
    strategy_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Execute active strategies against one enriched EOD snapshot.

    Data loading and strategy execution remain delegated to ScreenerService
    and StrategyEngine; this function only orchestrates candidate seed output.
    """
    if timeframe != "1d":
        raise EODRunnerError("EOD seeds only support the 1d timeframe")
    service = ScreenerService(repo, asset_type=asset_type)
    target = as_of or service.latest_date()
    if target is None:
        raise EODRunnerError("没有可用的 enriched 数据日期")

    available = {
        item["id"]: item
        for item in engine.list_strategies(include_research=False)
        if item.get("lifecycle", "active") == "active"
        and asset_type in item.get("asset_types", ["stock"])
        and timeframe in item.get("timeframes", ["1d"])
    }
    selected = list(available) if strategy_ids is None else list(strategy_ids)
    selected = [sid for sid in selected if sid in available]
    if not selected:
        return {
            "as_of": target.isoformat(),
            "asset_type": asset_type,
            "timeframe": timeframe,
            "strategies": 0,
            "seeds": 0,
            "candidates": 0,
            "elapsed_ms": 0.0,
            "data_quality": _quality(None, target).to_dict(),
        }

    overrides = {}
    from app.strategy import config as strategy_config

    for sid in selected:
        overrides[sid] = strategy_config.load_override(Path(data_dir), sid)
    params_map = {sid: dict(overrides[sid].get("params") or {}) for sid in selected}
    context = service.build_strategy_context(
        engine,
        target,
        selected,
        timeframe=timeframe,
        params_map=params_map,
        overrides_map=overrides,
    )
    quality = _quality(context.current, target)
    started = time.perf_counter()
    results = engine.run_all(
        context,
        params_map=params_map,
        overrides_map=overrides,
        strategy_ids=selected,
    )
    store = EODSeedStore(data_dir)
    written: list[dict[str, Any]] = []
    for sid in selected:
        batch = batch_from_result(results[sid])
        batch = type(batch)(
            model_version=batch.model_version,
            strategy_id=batch.strategy_id,
            as_of=batch.as_of,
            candidates=batch.candidates,
            provenance={
                **batch.provenance,
                "execution": "eod_seed",
                "data_quality": quality.to_dict(),
            },
            data_quality=quality.to_dict(),
            seed_id=batch.seed_id,
        )
        written.append(store.put(batch))
    elapsed = (time.perf_counter() - started) * 1000
    return {
        "as_of": target.isoformat(),
        "asset_type": asset_type,
        "timeframe": timeframe,
        "strategies": len(written),
        "seeds": len(written),
        "candidates": sum(len(item.get("candidates") or []) for item in written),
        "elapsed_ms": round(elapsed, 3),
        "data_quality": quality.to_dict(),
    }


def _quality(current: pl.DataFrame | None, as_of: date) -> DataQuality:
    if current is None or current.is_empty():
        return DataQuality.from_counts(
            "kline_daily_enriched",
            expected_rows=1,
            actual_rows=0,
        )
    actual = current.height
    expected = current["symbol"].n_unique() if "symbol" in current.columns else actual
    return DataQuality.from_counts(
        "kline_daily_enriched",
        expected_rows=max(1, int(expected)),
        actual_rows=actual,
    )
