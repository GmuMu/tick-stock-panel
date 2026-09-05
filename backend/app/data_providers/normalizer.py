"""Normalize provider responses into internal Polars schemas."""
from __future__ import annotations

import polars as pl

from app.data_providers.schemas import (
    normalize_amount,
    normalize_date,
    normalize_epoch_ms,
    normalize_exchange,
    normalize_price,
    normalize_symbol,
    normalize_volume,
)
from app.indicators.pipeline import filter_halt_days

DAILY_COLS = ["symbol", "date", "open", "high", "low", "close", "volume", "amount", "quote_ts"]
ADJ_FACTOR_COLS = ["symbol", "trade_date", "ex_factor"]
INSTRUMENT_COLS = ["symbol", "name", "code", "exchange", "asset_type", "source"]


def to_polars(data) -> pl.DataFrame:
    if data is None:
        return pl.DataFrame()
    if isinstance(data, pl.DataFrame):
        return data
    if isinstance(data, dict):
        rows: list[dict] = []
        for sym, values in data.items():
            for item in values or []:
                row = dict(item or {})
                row.setdefault("symbol", sym)
                rows.append(row)
        return pl.DataFrame(rows) if rows else pl.DataFrame()
    if hasattr(data, "reset_index"):
        return pl.from_pandas(data.reset_index())
    try:
        return pl.DataFrame(data)
    except Exception:
        return pl.DataFrame()


def normalize_daily(data, default_symbol: str | None = None, source: str = "tickflow") -> pl.DataFrame:
    df = to_polars(data)
    if df.is_empty():
        return df
    rename_map = {
        "ts_code": "symbol",
        "trade_date": "date",
        "datetime": "date",
        "vol": "volume",
        "amt": "amount",
        "timestamp": "quote_ts",
    }
    df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})
    if "symbol" not in df.columns and default_symbol:
        df = df.with_columns(pl.lit(default_symbol).alias("symbol"))
    if "symbol" in df.columns:
        df = df.with_columns(
            pl.col("symbol").map_elements(normalize_symbol, return_dtype=pl.Utf8).alias("symbol")
        )
    if "date" in df.columns:
        df = df.with_columns(
            pl.col("date").map_elements(normalize_date, return_dtype=pl.Date).alias("date")
        )
    # quote_ts: 毫秒级行情时间戳, 用于盘后校验/量比折算。保留为 Int64, 缺失则置 null。
    if "quote_ts" in df.columns:
        df = df.with_columns(
            pl.col("quote_ts").map_elements(normalize_epoch_ms, return_dtype=pl.Int64).alias("quote_ts")
        )
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col in df.columns:
            normalizer = normalize_volume if col == "volume" else normalize_amount if col == "amount" else normalize_price
            df = df.with_columns(
                pl.col(col).map_elements(normalizer, return_dtype=pl.Float64).alias(col)
            )
    df = filter_halt_days(df)
    keep = [c for c in DAILY_COLS if c in df.columns]
    return df.select(keep) if keep else pl.DataFrame()


def normalize_adj_factors(data, source: str = "tickflow") -> pl.DataFrame:
    df = to_polars(data)
    if df.is_empty():
        return df
    rename_map = {
        "timestamp": "trade_date",
        "date": "trade_date",
        "adj_factor": "ex_factor",
    }
    df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})
    if "symbol" in df.columns:
        df = df.with_columns(
            pl.col("symbol").map_elements(normalize_symbol, return_dtype=pl.Utf8).alias("symbol")
        )
    if "trade_date" in df.columns:
        df = df.with_columns(
            pl.col("trade_date").map_elements(normalize_date, return_dtype=pl.Date).alias("trade_date")
        )
    if "ex_factor" in df.columns:
        df = df.with_columns(
            pl.col("ex_factor").map_elements(normalize_price, return_dtype=pl.Float64).alias("ex_factor")
        )
    keep = [c for c in ADJ_FACTOR_COLS if c in df.columns]
    return df.select(keep).drop_nulls() if len(keep) == len(ADJ_FACTOR_COLS) else pl.DataFrame()


def normalize_instruments(rows: list[dict], asset_type: str, source: str = "tickflow") -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    out: list[dict] = []
    for item in rows:
        symbol = normalize_symbol(item.get("symbol"))
        if not symbol:
            continue
        exchange = item.get("exchange")
        if exchange:
            exchange = normalize_exchange(exchange) or str(exchange).strip().upper()
        else:
            exchange = symbol.rsplit(".", 1)[1] if "." in symbol else None
        out.append({
            "symbol": symbol,
            "name": item.get("name") or str(symbol),
            "code": item.get("code") or str(symbol).split(".")[0],
            "exchange": exchange,
            "asset_type": asset_type,
            "source": source,
        })
    if not out:
        return pl.DataFrame()
    return pl.DataFrame(out).select(INSTRUMENT_COLS).unique(subset=["symbol"], keep="last").sort("symbol")
