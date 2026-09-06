"""Single-stock box analysis built on the canonical daily K-line dataset.

This is an analysis aid, not an order-generation strategy.  The box uses the
previous ``lookback`` bars so the current bar can be classified as an
inside-bar, near-breakout, or breakout without leaking today's high/low into
the boundary.
"""
from __future__ import annotations

import math
from typing import Any

import polars as pl

DEFAULT_LOOKBACK = 60
MIN_LOOKBACK = 20
MAX_LOOKBACK = 250
DEFAULT_RECENT = 8


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _date_text(value: Any) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10]


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _classify(close: float, upper: float, lower: float) -> tuple[str, str]:
    width = upper - lower
    if close > upper:
        return "breakout_up", "向上突破"
    if close < lower:
        return "breakout_down", "向下跌破"
    if width <= 0:
        return "inside", "箱体数据不足"
    position = (close - lower) / width
    if position >= 0.8:
        return "near_upper", "接近箱体上沿"
    if position <= 0.2:
        return "near_lower", "接近箱体下沿"
    return "inside", "箱体运行中"


def _row_box(rows: list[dict[str, Any]], index: int, lookback: int) -> dict[str, Any] | None:
    if index < lookback:
        return None
    previous = rows[index - lookback:index]
    highs = [_finite(row.get("high")) for row in previous]
    lows = [_finite(row.get("low")) for row in previous]
    close = _finite(rows[index].get("close"))
    if close is None or not highs or not lows or any(v is None for v in highs + lows):
        return None
    upper = max(v for v in highs if v is not None)
    lower = min(v for v in lows if v is not None)
    if upper <= lower:
        return None
    width = upper - lower
    position = (close - lower) / width
    status, status_label = _classify(close, upper, lower)
    volumes = [_finite(row.get("volume")) for row in previous]
    valid_volumes = [value for value in volumes if value is not None and value >= 0]
    current_volume = _finite(rows[index].get("volume"))
    average_volume = sum(valid_volumes) / len(valid_volumes) if valid_volumes else None
    volume_ratio = (
        current_volume / average_volume
        if current_volume is not None and average_volume and average_volume > 0
        else None
    )
    return {
        "date": _date_text(rows[index].get("date")),
        "close": _round(close, 2),
        "upper": _round(upper, 2),
        "lower": _round(lower, 2),
        "middle": _round((upper + lower) / 2, 2),
        "position_pct": _round(position * 100, 2),
        "width_pct": _round(width / lower * 100, 2) if lower > 0 else None,
        "status": status,
        "status_label": status_label,
        "breakout_up": status == "breakout_up",
        "breakout_down": status == "breakout_down",
        "volume_ratio": _round(volume_ratio, 2),
        "volume_confirmed": bool(volume_ratio is not None and volume_ratio >= 1.2),
    }


def analyze_box(
    df: pl.DataFrame,
    *,
    symbol: str,
    lookback: int = DEFAULT_LOOKBACK,
    recent: int = DEFAULT_RECENT,
) -> dict[str, Any]:
    """Return a JSON-safe single-stock box analysis payload."""
    lookback = max(MIN_LOOKBACK, min(MAX_LOOKBACK, int(lookback)))
    recent = max(3, min(20, int(recent)))
    required = {"date", "high", "low", "close"}
    if df.is_empty() or not required.issubset(set(df.columns)):
        return {
            "symbol": symbol,
            "as_of": None,
            "lookback_days": lookback,
            "observations": 0,
            "current": None,
            "box": None,
            "volume": None,
            "score": None,
            "conditions": [],
            "recent": [],
            "box_series": [],
            "message": "暂无足够日K数据",
        }

    columns = [c for c in ["date", "open", "high", "low", "close", "volume", "amount", "ma20"] if c in df.columns]
    rows = df.sort("date").select(columns).to_dicts()
    classified: list[dict[str, Any]] = []
    for index in range(len(rows)):
        item = _row_box(rows, index, lookback)
        if item is not None:
            classified.append(item)

    if not classified:
        return {
            "symbol": symbol,
            "as_of": _date_text(rows[-1].get("date")),
            "lookback_days": lookback,
            "observations": len(rows),
            "current": None,
            "box": None,
            "volume": None,
            "score": None,
            "conditions": [],
            "recent": [],
            "box_series": [],
            "message": f"至少需要 {lookback + 1} 根有效日K",
        }

    current = classified[-1]
    latest_row = rows[-1]
    current_close = _finite(latest_row.get("close"))
    current_volume = _finite(latest_row.get("volume"))
    prior_volumes = [
        _finite(row.get("volume"))
        for row in rows[max(0, len(rows) - lookback - 5): -1]
    ]
    prior_volumes = [value for value in prior_volumes if value is not None and value >= 0]
    avg_volume = sum(prior_volumes) / len(prior_volumes) if prior_volumes else None
    volume_ratio = current_volume / avg_volume if current_volume is not None and avg_volume and avg_volume > 0 else None

    width_pct = current["width_pct"] or 0.0
    position_pct = current["position_pct"] or 0.0
    ma20 = _finite(latest_row.get("ma20"))
    if ma20 is None and len(rows) >= 20:
        closes = [_finite(row.get("close")) for row in rows[-20:]]
        valid_closes = [value for value in closes if value is not None]
        ma20 = sum(valid_closes) / len(valid_closes) if len(valid_closes) == 20 else None

    conditions = [
        {
            "key": "compact_box",
            "label": "箱体清晰",
            "passed": width_pct <= 15.0,
            "detail": f"箱体宽度 {width_pct:.2f}%",
        },
        {
            "key": "upper_position",
            "label": "价格靠近上沿",
            "passed": position_pct >= 70.0,
            "detail": f"当前位置 {position_pct:.2f}%",
        },
        {
            "key": "volume_confirmation",
            "label": "量能确认",
            "passed": volume_ratio is not None and volume_ratio >= 1.2,
            "detail": f"量比 {volume_ratio:.2f}" if volume_ratio is not None else "缺少成交量",
        },
        {
            "key": "above_ma20",
            "label": "站上20日均线",
            "passed": current_close is not None and ma20 is not None and current_close >= ma20,
            "detail": f"MA20 {ma20:.2f}" if ma20 is not None else "缺少MA20",
        },
    ]
    score = sum(25 for condition in conditions if condition["passed"])
    if current["status"] == "breakout_up":
        score = min(100, score + 10)
    elif current["status"] == "breakout_down":
        score = max(0, score - 20)

    current_payload = {
        "date": current["date"],
        "open": _round(_finite(latest_row.get("open")), 2),
        "high": _round(_finite(latest_row.get("high")), 2),
        "low": _round(_finite(latest_row.get("low")), 2),
        "close": _round(current_close, 2),
        "ma20": _round(ma20, 2),
    }
    volume_payload = {
        "current": _round(current_volume, 2),
        "average": _round(avg_volume, 2),
        "ratio": _round(volume_ratio, 2),
        "confirmed": bool(volume_ratio is not None and volume_ratio >= 1.2),
    }
    box_payload = {
        "upper": current["upper"],
        "lower": current["lower"],
        "middle": current["middle"],
        "width_pct": current["width_pct"],
        "position_pct": current["position_pct"],
        "status": current["status"],
        "status_label": current["status_label"],
        "breakout_up": current["status"] == "breakout_up",
        "breakout_down": current["status"] == "breakout_down",
    }
    return {
        "symbol": symbol,
        "as_of": current["date"],
        "lookback_days": lookback,
        "observations": len(rows),
        "current": current_payload,
        "box": box_payload,
        "volume": volume_payload,
        "score": score,
        "conditions": conditions,
        "recent": classified[-recent:],
        "box_series": classified[-MAX_LOOKBACK:],
        "message": "箱体分析仅用于研究,不构成投资或下单建议",
    }


def analyze_box_batch(
    frames: dict[str, pl.DataFrame],
    *,
    lookback: int = DEFAULT_LOOKBACK,
    recent: int = DEFAULT_RECENT,
) -> dict[str, dict[str, Any]]:
    """Analyze multiple symbols while preserving the caller's symbol order."""
    return {
        symbol: analyze_box(frame, symbol=symbol, lookback=lookback, recent=recent)
        for symbol, frame in frames.items()
    }
