"""Internal provider schemas and canonical market-data conversions."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

CN_TZ = timezone(timedelta(hours=8))

_EXCHANGE_ALIASES = {
    "SH": "SH",
    "SSE": "SH",
    "SHSE": "SH",
    "XSHG": "SH",
    "SZ": "SZ",
    "SZSE": "SZ",
    "XSHE": "SZ",
    "BJ": "BJ",
    "BSE": "BJ",
}


def normalize_exchange(value: object) -> str | None:
    """Normalize common Chinese exchange aliases to ``SH``, ``SZ`` or ``BJ``."""
    text = str(value or "").strip().upper()
    return _EXCHANGE_ALIASES.get(text)


def normalize_symbol(value: object) -> str | None:
    """Normalize common provider symbols to ``CODE.EXCHANGE``.

    Unknown formats are upper-cased and preserved rather than assigned an
    exchange by guesswork.
    """
    text = str(value or "").strip().upper()
    if not text:
        return None

    parts = re.split(r"[._-]", text)
    if len(parts) == 2:
        left, right = parts
        if (exchange := normalize_exchange(left)):
            return f"{right}.{exchange}"
        if (exchange := normalize_exchange(right)):
            return f"{left}.{exchange}"

    match = re.fullmatch(r"(SH|SSE|SHSE|XSHG|SZ|SZSE|XSHE|BJ|BSE)(\d+)", text)
    if match:
        return f"{match.group(2)}.{normalize_exchange(match.group(1))}"

    return text


def normalize_epoch_ms(value: object) -> int | None:
    """Normalize a timestamp to Unix epoch milliseconds.

    Naive datetimes are interpreted as Beijing wall-clock values. This keeps
    server timezone settings out of provider boundary conversions.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=CN_TZ)
        return int(dt.astimezone(UTC).timestamp() * 1000)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number)


def normalize_date(value: object) -> date | None:
    """Normalize provider date-like values to a Beijing calendar date."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=CN_TZ)
        return dt.astimezone(CN_TZ).date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        if float(value).is_integer() and 19_000_101 <= int(value) <= 29_991_231:
            try:
                return datetime.strptime(str(int(value)), "%Y%m%d").date()
            except ValueError:
                return None
        try:
            return datetime.fromtimestamp(float(value) / 1000, tz=CN_TZ).date()
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return normalize_date(float(text))
    try:
        return normalize_date(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _normalize_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_price(value: object) -> float | None:
    """Normalize a price in CNY to a finite float."""
    return _normalize_number(value)


def normalize_ratio(value: object, *, unit: str = "decimal") -> float | None:
    """Normalize a ratio to decimal form: ``0.05`` means five percent."""
    number = _normalize_number(value)
    if number is None:
        return None
    unit = str(unit or "decimal").strip().lower()
    if unit == "decimal":
        return number
    if unit == "percent":
        return number / 100
    raise ValueError("ratio unit must be percent or decimal")


def normalize_volume(value: object, *, unit: str = "lots") -> float | int | None:
    """Normalize volume to A-share lots (one lot is 100 shares)."""
    number = _normalize_number(value)
    if number is None:
        return None
    unit = str(unit or "lots").strip().lower()
    if unit == "lots":
        return number
    if unit == "shares":
        return math.floor(number / 100)
    raise ValueError("volume unit must be shares or lots")


def normalize_amount(value: object, *, unit: str = "yuan") -> float | None:
    """Normalize turnover to CNY yuan."""
    number = _normalize_number(value)
    if number is None:
        return None
    unit = str(unit or "yuan").strip().lower()
    if unit in {"yuan", "cny"}:
        return number
    if unit in {"wan_yuan", "10k_yuan", "ten_thousand_yuan"}:
        return number * 10_000
    raise ValueError("amount unit must be yuan or wan_yuan")


@dataclass(frozen=True)
class CanonicalQuoteMeta:
    """Immutable identity and time metadata shared by quote providers."""

    symbol: str
    trade_date: date | str | None = None
    quote_ts: int | float | datetime | str | None = None
    received_at: datetime | str | None = None

    def __post_init__(self) -> None:
        symbol = normalize_symbol(self.symbol)
        if symbol is None:
            raise ValueError("symbol is required")
        trade_date = normalize_date(self.trade_date)
        quote_ts = normalize_epoch_ms(self.quote_ts)
        received_at = self.received_at
        if received_at is not None:
            received_at = normalize_datetime(received_at)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "trade_date", trade_date)
        object.__setattr__(self, "quote_ts", quote_ts)
        object.__setattr__(self, "received_at", received_at)

    @property
    def quote_trade_day(self) -> date | None:
        """Beijing calendar day represented by ``quote_ts``."""
        return normalize_date(self.quote_ts) if self.quote_ts is not None else None


def normalize_datetime(value: datetime | str) -> datetime | None:
    """Normalize a datetime to timezone-aware UTC for transport metadata."""
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(text)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    dt = value if value.tzinfo is not None else value.replace(tzinfo=CN_TZ)
    return dt.astimezone(UTC)


DAILY_COLUMNS = [
    "symbol", "asset_type", "source", "date", "open", "high", "low", "close",
    "volume", "amount", "pre_close", "change_pct",
]

ADJ_FACTOR_COLUMNS = ["symbol", "asset_type", "source", "trade_date", "ex_factor"]

INSTRUMENT_COLUMNS = [
    "symbol", "name", "exchange", "asset_type", "source", "list_date", "status",
]

MINUTE_COLUMNS = [
    "symbol", "asset_type", "source", "datetime", "open", "high", "low", "close",
    "volume", "amount", "freq",
]
