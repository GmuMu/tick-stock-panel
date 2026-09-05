"""free-stockdb provider implementation.

Only this module knows the bridge response aliases.  Strategy, backtest and
service code continue to consume the canonical Provider contract.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import polars as pl

from app.data_providers.base import AssetType
from app.data_providers.normalizer import (
    normalize_adj_factors,
    normalize_daily,
    normalize_instruments,
)
from app.data_providers.schemas import (
    CN_TZ,
    normalize_datetime,
    normalize_epoch_ms,
    normalize_price,
    normalize_symbol,
    normalize_volume,
)
from app.plugins.freestockdb import bridge

logger = logging.getLogger(__name__)

_DATASETS = ("daily", "minute", "realtime", "adj_factor")
_MINUTE_COLUMNS = [
    "symbol", "datetime", "open", "high", "low", "close", "volume", "amount",
]


def _date_text(value: datetime | None) -> str | None:
    return value.date().isoformat() if value else None


def _first(row: dict, *keys: str):
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


def _symbol(row: dict, default: str | None = None) -> str | None:
    value = _first(row, "symbol", "ts_code", "thscode", "ticker", "code")
    normalized = normalize_symbol(value or default)
    if normalized and "." not in normalized:
        exchange = str(_first(row, "exchange", "market", "market_id") or "").upper()
        exchange = {"SSE": "SH", "SHSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(
            exchange, exchange
        )
        if exchange in {"SH", "SZ", "BJ"}:
            normalized = f"{normalized}.{exchange}"
    return normalized


def _date_alias(row: dict):
    return _first(row, "date", "trade_date", "datetime", "timestamp", "trade_time")


def _minute_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = normalize_datetime(value)
        return parsed.astimezone(CN_TZ) if parsed is not None else None
    if isinstance(value, str):
        parsed = normalize_datetime(value)
        if parsed is not None:
            return parsed.astimezone(CN_TZ)
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    timestamp = normalize_epoch_ms(value)
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp / 1000, tz=UTC).astimezone(CN_TZ)


def _canonical_minute(rows: list[dict]) -> pl.DataFrame:
    out: list[dict] = []
    for row in rows:
        symbol = _symbol(row)
        dt_value = _minute_datetime(_date_alias(row))
        if not symbol or dt_value is None:
            continue
        out.append({
            "symbol": symbol,
            "datetime": dt_value.replace(tzinfo=None),
            "open": normalize_price(_first(row, "open", "open_price")),
            "high": normalize_price(_first(row, "high", "high_price")),
            "low": normalize_price(_first(row, "low", "low_price")),
            "close": normalize_price(_first(row, "close", "close_price", "last_price")),
            "volume": normalize_volume(_first(row, "volume", "vol"), unit="shares"),
            "amount": normalize_price(_first(row, "amount", "amt", "turnover")),
        })
    if not out:
        return pl.DataFrame()
    return pl.DataFrame(out).select(_MINUTE_COLUMNS)


def _canonical_realtime(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        symbol = _symbol(row)
        if not symbol:
            continue
        last = normalize_price(_first(row, "last_price", "price", "last", "close"))
        prev = normalize_price(_first(row, "prev_close", "pre_close", "prev", "preclose"))
        change_pct = _first(row, "change_pct", "change_percent", "pct_chg", "涨跌幅")
        try:
            change_pct = float(change_pct) / 100 if change_pct is not None else None
        except (TypeError, ValueError):
            change_pct = None
        if change_pct is None and last is not None and prev not in (None, 0):
            change_pct = (last - prev) / prev
        out.append({
            "symbol": symbol,
            "name": _first(row, "name", "stock_name"),
            "last_price": last,
            "prev_close": prev,
            "open": normalize_price(_first(row, "open", "open_price")),
            "high": normalize_price(_first(row, "high", "high_price")),
            "low": normalize_price(_first(row, "low", "low_price")),
            "volume": normalize_volume(_first(row, "volume", "vol"), unit="shares"),
            "amount": normalize_price(_first(row, "amount", "amt", "turnover")),
            "change_pct": change_pct,
            "change_amount": (
                last - prev if last is not None and prev is not None else None
            ),
            "timestamp": normalize_epoch_ms(
                _first(row, "timestamp", "quote_ts", "time", "datetime")
            ),
        })
    return out


def _with_default_symbol(rows: list[dict], symbols: list[str]) -> list[dict]:
    if len(symbols) != 1:
        return rows
    default = symbols[0]
    return [
        {**row, "symbol": row.get("symbol") or default}
        for row in rows
    ]


def _canonical_daily(rows: list[dict]) -> list[dict]:
    return [
        {
            "symbol": _symbol(row),
            "date": _first(row, "date", "trade_date", "datetime"),
            "open": normalize_price(_first(row, "open", "open_price")),
            "high": normalize_price(_first(row, "high", "high_price")),
            "low": normalize_price(_first(row, "low", "low_price")),
            "close": normalize_price(_first(row, "close", "close_price")),
            "volume": normalize_volume(_first(row, "volume", "vol"), unit="shares"),
            "amount": normalize_price(_first(row, "amount", "amt", "turnover")),
        }
        for row in rows
    ]


def _canonical_adj_factors(rows: list[dict]) -> list[dict]:
    return [
        {
            "symbol": _symbol(row),
            "trade_date": _first(row, "trade_date", "date", "datetime"),
            "ex_factor": _first(row, "ex_factor", "adj_factor", "factor"),
        }
        for row in rows
    ]


def _canonical_instruments(rows: list[dict]) -> list[dict]:
    return [
        {
            "symbol": _symbol(row),
            "name": _first(row, "name", "stock_name"),
            "code": _first(row, "code", "ticker"),
            "exchange": _first(row, "exchange", "market"),
        }
        for row in rows
    ]


class FreeStockDBProvider:
    """Canonical provider backed by a free-stockdb HTTP service."""

    name = "freestockdb"
    builtin = True
    minute_history_days = None

    def __init__(self) -> None:
        self._client: bridge.FreeStockDBClient | None = None

    @property
    def config(self):
        class Config:
            name = "freestockdb"
            display_name = "free-stockdb"
            datasets = dict.fromkeys(_DATASETS)
            path = None
            builtin = True

        return Config()

    def _get_client(self) -> bridge.FreeStockDBClient:
        if self._client is None:
            self._client = bridge.FreeStockDBClient()
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def get_daily(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: AssetType = "stock",
        on_chunk_done: Callable[[int, int], None] | None = None,
    ) -> pl.DataFrame:
        if not symbols:
            return pl.DataFrame()
        rows = self._get_client().fetch_flat(
            "daily",
            symbols=symbols,
            start=_date_text(start_time),
            end=_date_text(end_time),
            asset_type=asset_type,
        )
        result = normalize_daily(
            _canonical_daily(_with_default_symbol(rows, symbols)),
            source=self.name,
        )
        if on_chunk_done:
            on_chunk_done(1, 1)
        return result

    def get_adj_factors(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: AssetType = "stock",
        on_chunk_done: Callable[[int, int], None] | None = None,
    ) -> pl.DataFrame:
        if not symbols:
            return pl.DataFrame()
        rows = self._get_client().fetch_flat(
            "adj_factor",
            symbols=symbols,
            start=_date_text(start_time),
            end=_date_text(end_time),
            asset_type=asset_type,
        )
        result = normalize_adj_factors(
            _canonical_adj_factors(_with_default_symbol(rows, symbols)),
            source=self.name,
        )
        if on_chunk_done:
            on_chunk_done(1, 1)
        return result

    def get_minute(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: AssetType = "stock",
        freq: str = "1m",
        on_chunk_done: Callable[[int, int], None] | None = None,
    ) -> pl.DataFrame:
        if not symbols:
            return pl.DataFrame()
        rows = self._get_client().fetch_flat(
            "minute",
            symbols=symbols,
            start=_date_text(start_time),
            end=_date_text(end_time),
            asset_type=asset_type,
            freq=freq,
        )
        result = _canonical_minute(_with_default_symbol(rows, symbols))
        if on_chunk_done:
            on_chunk_done(1, 1)
        return result

    def get_realtime(self) -> list[dict]:
        return _canonical_realtime(self._get_client().fetch_flat("realtime"))

    def get_instruments(self, asset_type: AssetType = "stock") -> pl.DataFrame:
        rows = self._get_client().fetch_flat("instruments", asset_type=asset_type)
        return normalize_instruments(
            _canonical_instruments(rows),
            asset_type=asset_type,
            source=self.name,
        )

    def test_dataset(self, dataset: str, symbols: list[str] | None = None) -> dict:
        if dataset not in _DATASETS:
            raise ValueError(f"free-stockdb 不支持数据集: {dataset}")
        syms = symbols or ["000001.SZ"]
        end = datetime.now()
        start = end - timedelta(days=7)
        if dataset == "daily":
            df = self.get_daily(syms, start, end)
            preview = df.head(5).to_dicts()
            columns = df.columns
            rows = df.height
        elif dataset == "adj_factor":
            df = self.get_adj_factors(syms, start, end)
            preview = df.head(5).to_dicts()
            columns = df.columns
            rows = df.height
        elif dataset == "minute":
            df = self.get_minute(syms, start, end)
            preview = df.head(5).to_dicts()
            columns = df.columns
            rows = df.height
        else:
            preview = self.get_realtime()[:5]
            columns = list(preview[0]) if preview else []
            rows = len(preview)
        for row in preview:
            for key, value in list(row.items()):
                if isinstance(value, (date, datetime)):
                    row[key] = value.isoformat()
        return {
            "provider": self.name,
            "dataset": dataset,
            "rows": rows,
            "columns": columns,
            "preview": preview,
        }
