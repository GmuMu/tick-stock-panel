"""缠论分析 V1。

实现目标是给个股分析页提供可解释的结构化图层:

* 先处理 K 线包含关系, 再计算分型;
* 用交替分型生成笔, 用三笔重叠生成线段/中枢候选;
* 依据已确认的笔和中枢生成研究型一/二/三类买卖点。

该模块只使用日 K, 不负责下单, 也不把未完成的最后一笔强行当成确认信号。
算法参数保持显式, 方便后续和更严格的 chan.py 配置逐项对齐。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

import polars as pl

DEFAULT_DAYS = 250
MIN_DAYS = 60
MAX_DAYS = 500
DEFAULT_MIN_BARS = 3


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


@dataclass
class _Bar:
    start: int
    end: int
    date: str
    high: float
    low: float
    close: float


@dataclass
class _Fractal:
    index: int
    kind: str
    date: str
    price: float


@dataclass
class _Bi:
    index: int
    start: _Fractal
    end: _Fractal
    direction: str
    high: float
    low: float


def _merge_bars(rows: list[dict[str, Any]]) -> list[_Bar]:
    """按方向处理包含关系, 保留合并 K 线覆盖的原始日期范围。"""
    bars: list[_Bar] = []
    for index, row in enumerate(rows):
        high = _finite(row.get("high"))
        low = _finite(row.get("low"))
        close = _finite(row.get("close"))
        if high is None or low is None or close is None or high < low:
            continue
        current = _Bar(
            start=index,
            end=index,
            date=_date_text(row.get("date")),
            high=high,
            low=low,
            close=close,
        )
        while bars:
            previous = bars[-1]
            contains = (
                current.high >= previous.high and current.low <= previous.low
            ) or (
                current.high <= previous.high and current.low >= previous.low
            )
            if not contains:
                break
            if len(bars) >= 2:
                prior = bars[-2]
                if previous.high >= prior.high and previous.low >= prior.low:
                    direction = "up"
                elif previous.high <= prior.high and previous.low <= prior.low:
                    direction = "down"
                else:
                    direction = "up" if previous.close >= prior.close else "down"
            else:
                direction = "up" if current.close >= previous.close else "down"
            if direction == "up":
                high = max(previous.high, current.high)
                low = max(previous.low, current.low)
            else:
                high = min(previous.high, current.high)
                low = min(previous.low, current.low)
            current = _Bar(
                start=previous.start,
                end=current.end,
                date=current.date,
                high=high,
                low=low,
                close=current.close,
            )
            bars.pop()
        bars.append(current)
    return bars


def _fractals(bars: list[_Bar]) -> list[_Fractal]:
    candidates: list[_Fractal] = []
    for index in range(1, len(bars) - 1):
        previous, current, following = bars[index - 1:index + 2]
        top = (
            current.high >= previous.high
            and current.high >= following.high
            and current.low >= previous.low
            and current.low >= following.low
        )
        bottom = (
            current.low <= previous.low
            and current.low <= following.low
            and current.high <= previous.high
            and current.high <= following.high
        )
        if top and not bottom:
            candidates.append(
                _Fractal(index, "top", current.date, current.high)
            )
        elif bottom and not top:
            candidates.append(
                _Fractal(index, "bottom", current.date, current.low)
            )

    # 分型必须交替; 同类连续分型只保留更极端的一个。
    result: list[_Fractal] = []
    for item in candidates:
        if not result:
            result.append(item)
            continue
        last = result[-1]
        if item.kind != last.kind:
            result.append(item)
            continue
        more_extreme = (
            item.price > last.price if item.kind == "top" else item.price < last.price
        )
        if more_extreme:
            result[-1] = item
    return result


def _bis(fractals: list[_Fractal], min_bars: int) -> list[_Bi]:
    result: list[_Bi] = []
    for current in fractals:
        if not result:
            result.append(
                _Bi(
                    index=0,
                    start=current,
                    end=current,
                    direction="",
                    high=current.price,
                    low=current.price,
                )
            )
            continue
        previous = result[-1].end
        distance = current.index - previous.index + 1
        if current.kind == previous.kind:
            continue
        if distance < min_bars:
            # 太近的相反分型不构成有效笔, 留给后续更远的分型。
            continue
        direction = "up" if previous.kind == "bottom" else "down"
        result.append(
            _Bi(
                index=len(result),
                start=previous,
                end=current,
                direction=direction,
                high=max(previous.price, current.price),
                low=min(previous.price, current.price),
            )
        )
    return [item for item in result if item.direction]


def _bi_payload(item: _Bi, rows: list[dict[str, Any]]) -> dict[str, Any]:
    start_price = item.start.price
    end_price = item.end.price
    change = end_price / start_price - 1 if start_price else None
    return {
        "index": item.index,
        "start_date": item.start.date,
        "end_date": item.end.date,
        "direction": item.direction,
        "start_price": _round(start_price, 2),
        "end_price": _round(end_price, 2),
        "high": _round(item.high, 2),
        "low": _round(item.low, 2),
        "change_pct": _round(change * 100 if change is not None else None, 2),
        "confirmed": True,
    }


def _segments(bis: list[_Bi], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """用三笔重叠确认线段候选, 同方向的后续笔延伸线段终点。"""
    result: list[dict[str, Any]] = []
    # 只返回最近 12 个候选窗口,但笔数不足 12 时也必须正常计算。
    begin = max(0, len(bis) - 12)
    for start in range(begin, len(bis) - 2):
        window = bis[start:start + 3]
        overlap_high = min(item.high for item in window)
        overlap_low = max(item.low for item in window)
        if overlap_high < overlap_low:
            continue
        end = window[-1]
        result.append(
            {
                "index": len(result),
                "start_date": window[0].start.date,
                "end_date": end.end.date,
                "direction": window[0].direction,
                "start_price": _round(window[0].start.price, 2),
                "end_price": _round(end.end.price, 2),
                "high": _round(max(item.high for item in window), 2),
                "low": _round(min(item.low for item in window), 2),
                "confirmed": True,
            }
        )
    return result


def _central_zones(
    bis: list[_Bi], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for start in range(len(bis) - 2):
        window = bis[start:start + 3]
        upper = min(item.high for item in window)
        lower = max(item.low for item in window)
        if upper < lower:
            continue
        start_date = window[0].start.date
        end_date = window[-1].end.date
        if result and start_date <= result[-1]["end_date"]:
            result[-1]["end_date"] = end_date
            result[-1]["upper"] = _round(max(result[-1]["upper"], upper), 2)
            result[-1]["lower"] = _round(min(result[-1]["lower"], lower), 2)
            result[-1]["bars"] += len(window)
            continue
        result.append(
            {
                "index": len(result),
                "start_date": start_date,
                "end_date": end_date,
                "upper": _round(upper, 2),
                "lower": _round(lower, 2),
                "middle": _round((upper + lower) / 2, 2),
                "bars": len(window),
                "confirmed": True,
            }
        )
    return result


def _volume_ratio(rows: list[dict[str, Any]], index: int) -> float | None:
    current = _finite(rows[index].get("volume"))
    previous = [
        _finite(row.get("volume"))
        for row in rows[max(0, index - 5):index]
    ]
    values = [value for value in previous if value is not None and value > 0]
    if current is None or not values:
        return None
    return current / (sum(values) / len(values))


def _rolling_mean(rows: list[dict[str, Any]], period: int) -> list[float | None]:
    values = [_finite(row.get("close")) for row in rows]
    result: list[float | None] = []
    for index in range(len(values)):
        window = [value for value in values[max(0, index - period + 1):index + 1] if value is not None]
        result.append(_round(sum(window) / period, 4) if len(window) == period else None)
    return result


def _ema(values: list[float | None], period: int) -> list[float | None]:
    result: list[float | None] = []
    previous: float | None = None
    alpha = 2 / (period + 1)
    for value in values:
        if value is None:
            result.append(None)
            continue
        previous = value if previous is None else alpha * value + (1 - alpha) * previous
        result.append(previous)
    return result


def _macd(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [_finite(row.get("close")) for row in rows]
    fast = _ema(closes, 12)
    slow = _ema(closes, 26)
    dif: list[float | None] = []
    for fast_value, slow_value in zip(fast, slow, strict=True):
        dif.append(
            _round(fast_value - slow_value, 4)
            if fast_value is not None and slow_value is not None
            else None
        )
    dea = _ema(dif, 9)
    hist = [
        _round(2 * (dif_value - dea_value), 4)
        if dif_value is not None and dea_value is not None
        else None
        for dif_value, dea_value in zip(dif, dea, strict=True)
    ]

    crosses: list[dict[str, Any]] = []
    for index in range(1, len(rows)):
        previous_dif = dif[index - 1]
        current_dif = dif[index]
        previous_dea = dea[index - 1]
        current_dea = dea[index]
        if None in (previous_dif, current_dif, previous_dea, current_dea):
            continue
        kind: str | None = None
        if previous_dif <= previous_dea and current_dif > current_dea:
            kind = "golden_cross"
        elif previous_dif >= previous_dea and current_dif < current_dea:
            kind = "dead_cross"
        if kind is None:
            continue
        crosses.append(
            {
                "date": _date_text(rows[index].get("date")),
                "price": _round(_finite(rows[index].get("close")), 2),
                "type": kind,
                "label": "MACD金叉" if kind == "golden_cross" else "MACD死叉",
                "side": "buy" if kind == "golden_cross" else "sell",
                "dif": _round(current_dif, 4),
                "dea": _round(current_dea, 4),
                "confirmed": True,
            }
        )

    return {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
        "dif": [_round(value, 4) for value in dif],
        "dea": [_round(value, 4) for value in dea],
        "hist": [_round(value, 4) for value in hist],
        "crosses": crosses[-60:],
    }


def _wilder_ema(values: list[float | None], period: int) -> list[float | None]:
    """Wilder 平滑, 与现有 enriched RSI 的 alpha=1/N 口径保持一致。"""
    result: list[float | None] = []
    previous: float | None = None
    alpha = 1 / period
    for value in values:
        if value is None:
            result.append(None)
            continue
        previous = value if previous is None else alpha * value + (1 - alpha) * previous
        result.append(previous)
    return result


def _rsi(rows: list[dict[str, Any]], period: int = 14) -> dict[str, Any]:
    closes = [_finite(row.get("close")) for row in rows]
    gains: list[float | None] = [None]
    losses: list[float | None] = [None]
    for index in range(1, len(closes)):
        previous, current = closes[index - 1], closes[index]
        if previous is None or current is None:
            gains.append(None)
            losses.append(None)
            continue
        delta = current - previous
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = _wilder_ema(gains, period)
    avg_loss = _wilder_ema(losses, period)
    values: list[float | None] = []
    for gain, loss in zip(avg_gain, avg_loss, strict=True):
        if gain is None or loss is None:
            values.append(None)
        elif loss == 0:
            values.append(100.0 if gain > 0 else 50.0)
        else:
            values.append(_round(100 - 100 / (1 + gain / loss), 2))

    signals: list[dict[str, Any]] = []
    for index in range(1, len(rows)):
        previous, current = values[index - 1], values[index]
        if previous is None or current is None:
            continue
        kind: str | None = None
        if previous < 30 <= current:
            kind = "rsi_oversold_recovery"
        elif previous > 70 >= current:
            kind = "rsi_overbought_fall"
        elif previous <= 50 < current:
            kind = "rsi_midline_up"
        elif previous >= 50 > current:
            kind = "rsi_midline_down"
        if kind is None:
            continue
        is_buy = kind in {"rsi_oversold_recovery", "rsi_midline_up"}
        labels = {
            "rsi_oversold_recovery": "RSI脱离超卖",
            "rsi_overbought_fall": "RSI脱离超买",
            "rsi_midline_up": "RSI上穿50",
            "rsi_midline_down": "RSI下破50",
        }
        signals.append(
            {
                "date": _date_text(rows[index].get("date")),
                "price": _round(_finite(rows[index].get("close")), 2),
                "type": kind,
                "label": labels[kind],
                "side": "buy" if is_buy else "sell",
                "level": 30 if kind == "rsi_oversold_recovery" else 70
                if kind == "rsi_overbought_fall" else 50,
                "reason": "RSI由关键阈值反向穿越",
                "confirmed": True,
            }
        )
    return {
        "period": period,
        "overbought": 70,
        "oversold": 30,
        "midline": 50,
        "values": values,
        "signals": signals[-60:],
    }


def _kdj(rows: list[dict[str, Any]], period: int = 9) -> dict[str, Any]:
    highs = [_finite(row.get("high")) for row in rows]
    lows = [_finite(row.get("low")) for row in rows]
    closes = [_finite(row.get("close")) for row in rows]
    k_values: list[float | None] = []
    d_values: list[float | None] = []
    j_values: list[float | None] = []
    previous_k: float | None = None
    previous_d: float | None = None
    for index in range(len(rows)):
        window_highs = [value for value in highs[max(0, index - period + 1):index + 1] if value is not None]
        window_lows = [value for value in lows[max(0, index - period + 1):index + 1] if value is not None]
        close = closes[index]
        if len(window_highs) < period or len(window_lows) < period or close is None:
            k_values.append(None)
            d_values.append(None)
            j_values.append(None)
            continue
        highest, lowest = max(window_highs), min(window_lows)
        rsv = 50.0 if highest == lowest else (close - lowest) / (highest - lowest) * 100
        current_k = rsv if previous_k is None else (2 * previous_k + rsv) / 3
        current_d = current_k if previous_d is None else (2 * previous_d + current_k) / 3
        current_j = 3 * current_k - 2 * current_d
        k_values.append(_round(current_k, 2))
        d_values.append(_round(current_d, 2))
        j_values.append(_round(current_j, 2))
        previous_k, previous_d = current_k, current_d

    signals: list[dict[str, Any]] = []
    for index in range(1, len(rows)):
        previous_k, current_k = k_values[index - 1], k_values[index]
        previous_d, current_d = d_values[index - 1], d_values[index]
        if None in (previous_k, current_k, previous_d, current_d):
            continue
        kind: str | None = None
        if previous_k <= previous_d and current_k > current_d:
            kind = "kdj_golden_cross"
        elif previous_k >= previous_d and current_k < current_d:
            kind = "kdj_dead_cross"
        if kind is None:
            continue
        is_buy = kind == "kdj_golden_cross"
        signals.append(
            {
                "date": _date_text(rows[index].get("date")),
                "price": _round(_finite(rows[index].get("close")), 2),
                "type": kind,
                "label": "KDJ金叉" if is_buy else "KDJ死叉",
                "side": "buy" if is_buy else "sell",
                "level": _round(current_k, 2),
                "reason": "K线与D线交叉",
                "confirmed": True,
            }
        )
    return {
        "period": period,
        "smooth_k": 3,
        "smooth_d": 3,
        "k": k_values,
        "d": d_values,
        "j": j_values,
        "signals": signals[-60:],
    }


def _demark(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """TD/Demark 研究型计数, 只输出已收盘 K 线确认的 9/13 节点。"""
    closes = [_finite(row.get("close")) for row in rows]
    highs = [_finite(row.get("high")) for row in rows]
    lows = [_finite(row.get("low")) for row in rows]
    setup: list[int] = []
    countdown: list[int] = []
    tdst_resistance: list[float | None] = []
    tdst_support: list[float | None] = []
    signals: list[dict[str, Any]] = []
    phase: str | None = None
    count = 0
    resistance: float | None = None
    support: float | None = None

    for index, close in enumerate(closes):
        previous_setup = setup[-1] if setup else 0
        if index < 4 or close is None or closes[index - 4] is None:
            current_setup = 0
        elif close > closes[index - 4]:
            current_setup = previous_setup + 1 if previous_setup >= 0 else 1
        elif close < closes[index - 4]:
            current_setup = previous_setup - 1 if previous_setup <= 0 else -1
        else:
            current_setup = 0
        setup.append(current_setup)

        if current_setup == 9 and index >= 8:
            phase, count = "sell", 0
            window_highs = [value for value in highs[index - 8:index + 1] if value is not None]
            resistance = max(window_highs) if window_highs else resistance
            signals.append(
                {
                    "date": _date_text(rows[index].get("date")),
                    "price": _round(close, 2),
                    "type": "demark_sell_setup_9",
                    "label": "TD卖出9",
                    "side": "sell",
                    "reason": "连续9根收盘价高于四根之前收盘价",
                    "confirmed": True,
                }
            )
        elif current_setup == -9 and index >= 8:
            phase, count = "buy", 0
            window_lows = [value for value in lows[index - 8:index + 1] if value is not None]
            support = min(window_lows) if window_lows else support
            signals.append(
                {
                    "date": _date_text(rows[index].get("date")),
                    "price": _round(close, 2),
                    "type": "demark_buy_setup_9",
                    "label": "TD买入9",
                    "side": "buy",
                    "reason": "连续9根收盘价低于四根之前收盘价",
                    "confirmed": True,
                }
            )
        elif phase == "sell" and index >= 2 and close is not None and closes[index - 2] is not None:
            if close >= closes[index - 2]:
                count += 1
        elif phase == "buy" and index >= 2 and close is not None and closes[index - 2] is not None:
            if close <= closes[index - 2]:
                count += 1

        countdown.append(min(count, 13))
        tdst_resistance.append(_round(resistance, 2))
        tdst_support.append(_round(support, 2))
        if count == 13:
            signals.append(
                {
                    "date": _date_text(rows[index].get("date")),
                    "price": _round(close, 2),
                    "type": f"demark_{phase}_countdown_13",
                    "label": "TD卖出13" if phase == "sell" else "TD买入13",
                    "side": "sell" if phase == "sell" else "buy",
                    "reason": "完成13计数, 仅作为趋势衰竭研究提示",
                    "confirmed": True,
                }
            )
            phase = None
    return {
        "setup": setup,
        "countdown": countdown,
        "tdst_resistance": tdst_resistance,
        "tdst_support": tdst_support,
        "signals": signals[-60:],
    }


def _channel(rows: list[dict[str, Any]], period: int = 20) -> dict[str, Any]:
    upper: list[float | None] = []
    lower: list[float | None] = []
    for index in range(len(rows)):
        highs = [
            value for value in
            (_finite(row.get("high")) for row in rows[max(0, index - period + 1):index + 1])
            if value is not None
        ]
        lows = [
            value for value in
            (_finite(row.get("low")) for row in rows[max(0, index - period + 1):index + 1])
            if value is not None
        ]
        upper.append(_round(max(highs), 2) if len(highs) == period else None)
        lower.append(_round(min(lows), 2) if len(lows) == period else None)

    breakouts: list[dict[str, Any]] = []
    for index in range(1, len(rows)):
        close = _finite(rows[index].get("close"))
        previous_upper = upper[index - 1]
        previous_lower = lower[index - 1]
        previous_close = _finite(rows[index - 1].get("close"))
        if None in (close, previous_close):
            continue
        if previous_upper is not None and previous_close <= previous_upper and close > previous_upper:
            breakouts.append(
                {
                    "date": _date_text(rows[index].get("date")),
                    "price": _round(close, 2),
                    "type": "channel_breakout_up",
                    "label": "上破通道",
                    "side": "buy",
                    "level": previous_upper,
                    "confirmed": True,
                }
            )
        elif previous_lower is not None and previous_close >= previous_lower and close < previous_lower:
            breakouts.append(
                {
                    "date": _date_text(rows[index].get("date")),
                    "price": _round(close, 2),
                    "type": "channel_breakout_down",
                    "label": "下破通道",
                    "side": "sell",
                    "level": previous_lower,
                    "confirmed": True,
                }
            )

    return {
        "period": period,
        "upper": upper,
        "lower": lower,
        "breakouts": breakouts[-40:],
    }


def _trendlines(fractals: list[_Fractal]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for kind, label in (("top", "上趋势线"), ("bottom", "下趋势线")):
        same_kind = [item for item in fractals if item.kind == kind]
        if len(same_kind) < 2:
            continue
        start, end = same_kind[-2:]
        distance = end.index - start.index
        if distance <= 0:
            continue
        slope = (end.price - start.price) / distance
        result.append(
            {
                "type": "resistance" if kind == "top" else "support",
                "label": label,
                "start_date": start.date,
                "end_date": end.date,
                "start_price": _round(start.price, 2),
                "end_price": _round(end.price, 2),
                "slope": _round(slope, 6),
                "confirmed": True,
            }
        )
    return result


def _eigen_sequences(bis: list[_Bi]) -> list[dict[str, Any]]:
    """暴露三笔特征序列, 供前端显示类似 chan.py 的特征区间。"""
    result: list[dict[str, Any]] = []
    for index in range(len(bis) - 2):
        window = bis[index:index + 3]
        overlap_high = min(item.high for item in window)
        overlap_low = max(item.low for item in window)
        result.append(
            {
                "index": index,
                "start_date": window[0].start.date,
                "end_date": window[-1].end.date,
                "high": _round(max(item.high for item in window), 2),
                "low": _round(min(item.low for item in window), 2),
                "direction": window[1].direction,
                "overlap": overlap_high >= overlap_low,
                "gap": overlap_high < overlap_low,
                "confirmed": True,
            }
        )
    return result[-60:]


def _divergences(
    bis: list[_Bi],
    macd: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    hist = macd.get("hist") or []
    row_index_by_date = {
        _date_text(row.get("date")): index
        for index, row in enumerate(rows)
    }
    result: list[dict[str, Any]] = []
    for index in range(2, len(bis)):
        previous = bis[index - 2]
        current = bis[index]
        previous_row = row_index_by_date.get(previous.end.date)
        current_row = row_index_by_date.get(current.end.date)
        if previous_row is None or current_row is None:
            continue
        previous_hist = hist[previous_row] if previous_row < len(hist) else None
        current_hist = hist[current_row] if current_row < len(hist) else None
        if previous_hist is None or current_hist is None:
            continue
        if current.direction == "down" and current.low < previous.low and abs(current_hist) < abs(previous_hist):
            result.append(
                {
                    "date": current.end.date,
                    "price": _round(current.end.price, 2),
                    "type": "bullish_divergence",
                    "label": "底背驰",
                    "side": "buy",
                    "reason": "笔创新低但 MACD 柱体动能减弱",
                    "confirmed": True,
                }
            )
        elif current.direction == "up" and current.high > previous.high and abs(current_hist) < abs(previous_hist):
            result.append(
                {
                    "date": current.end.date,
                    "price": _round(current.end.price, 2),
                    "type": "bearish_divergence",
                    "label": "顶背驰",
                    "side": "sell",
                    "reason": "笔创新高但 MACD 柱体动能减弱",
                    "confirmed": True,
                }
            )
    return result[-40:]


def _segment_signals(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """用相邻已确认线段给出线段级转折提示, 不替代严格 cbsp 算法。"""
    result: list[dict[str, Any]] = []
    for index in range(1, len(segments)):
        previous, current = segments[index - 1], segments[index]
        if previous["direction"] == current["direction"]:
            continue
        current_price = current.get("end_price")
        previous_price = previous.get("end_price")
        if current_price is None or previous_price is None:
            continue
        if current["direction"] == "up" and current_price > previous_price:
            result.append(
                {
                    "date": current["end_date"],
                    "price": current_price,
                    "type": "segment_buy",
                    "label": "线段买点",
                    "side": "buy",
                    "reason": "向上线段突破前一线段终点",
                    "confirmed": True,
                }
            )
        elif current["direction"] == "down" and current_price < previous_price:
            result.append(
                {
                    "date": current["end_date"],
                    "price": current_price,
                    "type": "segment_sell",
                    "label": "线段卖点",
                    "side": "sell",
                    "reason": "向下线段跌破前一线段终点",
                    "confirmed": True,
                }
            )
    return result[-40:]


def _segment_zones(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """输出 segzs 风格的线段级重叠区, 用于区别于笔级中枢。"""
    result: list[dict[str, Any]] = []
    for index in range(len(segments) - 2):
        window = segments[index:index + 3]
        upper = min(item["high"] for item in window)
        lower = max(item["low"] for item in window)
        if upper < lower:
            continue
        result.append(
            {
                "index": len(result),
                "start_date": window[0]["start_date"],
                "end_date": window[-1]["end_date"],
                "upper": _round(upper, 2),
                "lower": _round(lower, 2),
                "middle": _round((upper + lower) / 2, 2),
                "segments": 3,
                "confirmed": True,
            }
        )
    return result[-20:]


def _resample_rows(rows: list[dict[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    """把日线聚合为周线/月线, 每个周期只使用自身已结束的交易日。"""
    if timeframe == "1d":
        return rows
    groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        try:
            current_date = date.fromisoformat(_date_text(row.get("date")))
        except ValueError:
            continue
        if timeframe == "1w":
            iso = current_date.isocalendar()
            key = (iso.year, iso.week)
        elif timeframe == "1M":
            key = (current_date.year, current_date.month)
        else:
            continue
        groups.setdefault(key, []).append(row)

    grouped_items = list(groups.values())
    # 当前周/月可能仍在形成, 不把未闭合的高周期 K 线用于区间套确认。
    if grouped_items:
        grouped_items = grouped_items[:-1]

    result: list[dict[str, Any]] = []
    for items in grouped_items:
        first, last = items[0], items[-1]
        highs = [_finite(item.get("high")) for item in items]
        lows = [_finite(item.get("low")) for item in items]
        closes = [_finite(item.get("close")) for item in items]
        valid_highs = [value for value in highs if value is not None]
        valid_lows = [value for value in lows if value is not None]
        valid_closes = [value for value in closes if value is not None]
        if not valid_highs or not valid_lows or not valid_closes:
            continue
        payload: dict[str, Any] = {
            "date": last.get("date"),
            "open": _finite(first.get("open")) if first.get("open") is not None else valid_closes[0],
            "high": max(valid_highs),
            "low": min(valid_lows),
            "close": valid_closes[-1],
        }
        volumes = [_finite(item.get("volume")) for item in items]
        valid_volumes = [value for value in volumes if value is not None]
        if valid_volumes:
            payload["volume"] = sum(valid_volumes)
        result.append(payload)
    return result


def _strict_cbsp_points(
    bis: list[_Bi],
    zones: list[dict[str, Any]],
    macd: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """严格研究型 CBSP: 结构确认 + 动能背驰 + 中枢关系, 不提前标未完成点。"""
    hist = macd.get("hist") or []
    row_index_by_date = {
        _date_text(row.get("date")): index
        for index, row in enumerate(rows)
    }

    def hist_at(fractal: _Fractal) -> float | None:
        index = row_index_by_date.get(fractal.date)
        return hist[index] if index is not None and index < len(hist) else None

    def confirmed_zone(fractal: _Fractal) -> dict[str, Any] | None:
        candidates = [
            zone for zone in zones
            if zone["start_date"] <= fractal.date
            and zone["end_date"] <= fractal.date
        ]
        return candidates[-1] if candidates else None

    result: list[dict[str, Any]] = []
    for index in range(1, len(bis)):
        previous = bis[index - 1]
        current = bis[index]
        if previous.direction == current.direction:
            continue
        zone = confirmed_zone(previous.end)

        if current.direction == "up":
            same_direction = bis[index - 3] if index >= 3 else None
            if same_direction is not None and same_direction.direction == "down":
                previous_hist = hist_at(previous.end)
                same_hist = hist_at(same_direction.end)
                bullish_divergence = (
                    previous.low <= same_direction.low
                    and previous_hist is not None
                    and same_hist is not None
                    and abs(previous_hist) < abs(same_hist)
                )
                if bullish_divergence and current.end.price > previous.end.price:
                    result.append(
                        {
                            "date": current.end.date,
                            "price": _round(current.end.price, 2),
                            "side": "buy",
                            "type": "B1",
                            "label": "严格一买",
                            "reason": "下跌笔创新低且 MACD 动能衰减, 反向笔完成确认",
                            "basis": "divergence_reversal",
                            "level": "1b",
                            "confirmed": True,
                        }
                    )
                    continue

            if index < 2:
                continue
            prior = bis[index - 2]
            if prior.direction != "up":
                continue
            if (
                zone is not None
                and previous.low > prior.low
                and previous.low <= zone["upper"]
                and current.end.price > previous.end.price
            ):
                    result.append(
                        {
                            "date": current.end.date,
                            "price": _round(current.end.price, 2),
                            "side": "buy",
                            "type": "B2",
                            "label": "严格二买",
                            "reason": "回调低点抬高且未有效跌破确认中枢, 向上笔完成确认",
                            "basis": "higher_low_inside_zone",
                            "level": "2b",
                            "zone_index": zone["index"],
                            "confirmed": True,
                        }
                    )
                    continue
            prior_zone = confirmed_zone(prior.end)
            if (
                prior_zone is not None
                and prior.end.price > prior_zone["upper"]
                and previous.low > prior_zone["upper"]
                and current.end.price > prior.end.price
            ):
                result.append(
                    {
                        "date": current.end.date,
                        "price": _round(current.end.price, 2),
                        "side": "buy",
                        "type": "B3",
                        "label": "严格三买",
                        "reason": "向上离开确认中枢, 回抽不回中枢且再次突破",
                        "basis": "breakout_pullback",
                        "level": "3b",
                        "zone_index": prior_zone["index"],
                        "confirmed": True,
                    }
                )
        else:
            same_direction = bis[index - 3] if index >= 3 else None
            if same_direction is not None and same_direction.direction == "up":
                previous_hist = hist_at(previous.end)
                same_hist = hist_at(same_direction.end)
                bearish_divergence = (
                    previous.high >= same_direction.high
                    and previous_hist is not None
                    and same_hist is not None
                    and abs(previous_hist) < abs(same_hist)
                )
                if bearish_divergence and current.end.price < previous.end.price:
                    result.append(
                        {
                            "date": current.end.date,
                            "price": _round(current.end.price, 2),
                            "side": "sell",
                            "type": "S1",
                            "label": "严格一卖",
                            "reason": "上涨笔创新高且 MACD 动能衰减, 反向笔完成确认",
                            "basis": "divergence_reversal",
                            "level": "1s",
                            "confirmed": True,
                        }
                    )
                    continue

            if index < 2:
                continue
            prior = bis[index - 2]
            if prior.direction != "down":
                continue
            if (
                zone is not None
                and previous.high < prior.high
                and previous.high >= zone["lower"]
                and current.end.price < previous.end.price
            ):
                    result.append(
                        {
                            "date": current.end.date,
                            "price": _round(current.end.price, 2),
                            "side": "sell",
                            "type": "S2",
                            "label": "严格二卖",
                            "reason": "反弹高点降低且未有效突破确认中枢, 向下笔完成确认",
                            "basis": "lower_high_inside_zone",
                            "level": "2s",
                            "zone_index": zone["index"],
                            "confirmed": True,
                        }
                    )
                    continue
            prior_zone = confirmed_zone(prior.end)
            if (
                prior_zone is not None
                and prior.end.price < prior_zone["lower"]
                and previous.high < prior_zone["lower"]
                and current.end.price < prior.end.price
            ):
                result.append(
                    {
                        "date": current.end.date,
                        "price": _round(current.end.price, 2),
                        "side": "sell",
                        "type": "S3",
                        "label": "严格三卖",
                        "reason": "向下离开确认中枢, 回抽不回中枢且再次跌破",
                        "basis": "breakdown_pullback",
                        "level": "3s",
                        "zone_index": prior_zone["index"],
                        "confirmed": True,
                    }
                )

    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for point in result:
        unique[(point["date"], point["type"])] = point
    return sorted(unique.values(), key=lambda item: (item["date"], item["type"]))[-40:]


def _interval_nesting(
    cbsp_points: list[dict[str, Any]],
    multi_level: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """只把低级别信号嵌入已完成的高级别中枢, 避免高周期未来函数。"""
    result: list[dict[str, Any]] = []
    for point in cbsp_points:
        for timeframe, higher in multi_level.items():
            if timeframe == "1d":
                continue
            parent_zones = [
                zone for zone in higher.get("zones", [])
                if zone["end_date"] <= point["date"]
                and zone["lower"] <= point["price"] <= zone["upper"]
            ]
            if not parent_zones:
                continue
            parent = parent_zones[-1]
            last_bi = next(
                (
                    item for item in reversed(higher.get("bis", []))
                    if item["end_date"] <= point["date"]
                ),
                None,
            )
            direction_alignment = (
                last_bi is not None
                and (
                    (point["side"] == "buy" and last_bi["direction"] == "up")
                    or (point["side"] == "sell" and last_bi["direction"] == "down")
                )
            )
            result.append(
                {
                    "date": point["date"],
                    "price": point["price"],
                    "side": point["side"],
                    "type": point["type"],
                    "label": f"{timeframe}区间套",
                    "child_type": point["type"],
                    "child_timeframe": "1d",
                    "parent_timeframe": timeframe,
                    "parent_zone_index": parent["index"],
                    "parent_zone_upper": parent["upper"],
                    "parent_zone_lower": parent["lower"],
                    "direction_alignment": direction_alignment,
                    "confirmed": True,
                }
            )
    return result[-60:]


def _buy_sell_points(
    bis: list[_Bi],
    zones: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    row_index_by_date = {
        _date_text(row.get("date")): index
        for index, row in enumerate(rows)
    }
    for index, item in enumerate(bis):
        date = item.end.date
        price = item.end.price
        nearby = next(
            (
                zone
                for zone in reversed(zones)
                if zone["start_date"] <= date
            ),
            None,
        )
        if nearby is None or index == 0:
            continue
        previous = bis[index - 1]
        if item.direction == "up" and previous.direction == "down" and price > nearby["upper"]:
            points.append(
                {
                    "date": date,
                    "price": _round(price, 2),
                    "side": "buy",
                    "type": "B3",
                    "label": "三买",
                    "reason": "向上离开中枢并站稳中枢上沿",
                    "confirmed": True,
                }
            )
        elif item.direction == "down" and previous.direction == "up" and price < nearby["lower"]:
            points.append(
                {
                    "date": date,
                    "price": _round(price, 2),
                    "side": "sell",
                    "type": "S3",
                    "label": "三卖",
                    "reason": "向下离开中枢并跌破中枢下沿",
                    "confirmed": True,
                }
            )

        if index < 2:
            continue
        prior_same = bis[index - 2]
        if (
            item.direction == "up"
            and previous.direction == "down"
            and item.end.price > prior_same.end.price
            and price <= nearby["upper"]
        ):
            points.append(
                {
                    "date": date,
                    "price": _round(price, 2),
                    "side": "buy",
                    "type": "B2",
                    "label": "二买",
                    "reason": "回调不破前低, 中枢下方形成背驰式转折",
                    "confirmed": True,
                }
            )
        elif (
            item.direction == "down"
            and previous.direction == "up"
            and item.end.price < prior_same.end.price
            and price >= nearby["lower"]
        ):
            points.append(
                {
                    "date": date,
                    "price": _round(price, 2),
                    "side": "sell",
                    "type": "S2",
                    "label": "二卖",
                    "reason": "反弹不创新高, 中枢上方形成背驰式转折",
                    "confirmed": True,
                }
            )

    # 一买/一卖只在明确跌破/突破后再出现反向笔时确认, 避免标出未完成转折。
    for index in range(1, len(bis)):
        previous, current = bis[index - 1:index + 1]
        if previous.direction == current.direction:
            continue
        date = current.end.date
        price = current.end.price
        ratio = _volume_ratio(rows, row_index_by_date.get(date, len(rows) - 1))
        if current.direction == "up" and previous.low < min(
            (zone["lower"] for zone in zones if zone["start_date"] <= date),
            default=previous.low,
        ):
            points.append(
                {
                    "date": date,
                    "price": _round(price, 2),
                    "side": "buy",
                    "type": "B1",
                    "label": "一买",
                    "reason": "下跌趋势结束后出现向上确认笔",
                    "volume_ratio": _round(ratio, 2),
                    "confirmed": True,
                }
            )
        elif current.direction == "down" and previous.high > max(
            (zone["upper"] for zone in zones if zone["start_date"] <= date),
            default=previous.high,
        ):
            points.append(
                {
                    "date": date,
                    "price": _round(price, 2),
                    "side": "sell",
                    "type": "S1",
                    "label": "一卖",
                    "reason": "上涨趋势结束后出现向下确认笔",
                    "volume_ratio": _round(ratio, 2),
                    "confirmed": True,
                }
            )
    # 同一日期/类型只保留一个, 结果按日期和类型稳定排序。
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for point in points:
        unique[(point["date"], point["type"])] = point
    return sorted(unique.values(), key=lambda item: (item["date"], item["type"]))


def analyze_chan(
    df: pl.DataFrame,
    *,
    symbol: str,
    min_bars: int = DEFAULT_MIN_BARS,
    timeframes: tuple[str, ...] = ("1d", "1w", "1M"),
) -> dict[str, Any]:
    """返回可直接供个股分析图层消费的缠论结构。"""
    min_bars = max(3, min(10, int(min_bars)))
    requested_timeframes = tuple(
        dict.fromkeys(timeframe for timeframe in timeframes if timeframe in {"1d", "1w", "1M"})
    ) or ("1d",)
    required = {"date", "high", "low", "close"}
    if df.is_empty() or not required.issubset(set(df.columns)):
        return {
            "symbol": symbol,
            "as_of": None,
            "bars": 0,
            "merged_bars": [],
            "fractals": [],
            "bis": [],
            "segments": [],
            "zones": [],
            "points": [],
            "cbsp_points": [],
            "eigen": [],
            "trendlines": [],
            "moving_averages": {},
            "macd": {"dif": [], "dea": [], "hist": [], "crosses": []},
            "rsi": {"period": 14, "values": [], "signals": []},
            "kdj": {"period": 9, "smooth_k": 3, "smooth_d": 3, "k": [], "d": [], "j": [], "signals": []},
            "demark": {"setup": [], "countdown": [], "tdst_resistance": [], "tdst_support": [], "signals": []},
            "channel": {"period": 20, "upper": [], "lower": [], "breakouts": []},
            "divergences": [],
            "segment_signals": [],
            "segment_zones": [],
            "signals": [],
            "timeframes": list(requested_timeframes),
            "multi_level": {},
            "interval_nesting": [],
            "current": None,
            "message": "暂无足够日K数据",
        }

    columns = [
        column for column in
        ["date", "open", "high", "low", "close", "volume"]
        if column in df.columns
    ]
    rows = df.sort("date").select(columns).to_dicts()
    bars = _merge_bars(rows)
    fractals = _fractals(bars)
    bis = _bis(fractals, min_bars)
    zones = _central_zones(bis, rows)
    segments = _segments(bis, rows)
    points = _buy_sell_points(bis, zones, rows)
    segment_signals = _segment_signals(segments)
    segment_zones = _segment_zones(segments)

    latest = rows[-1]
    latest_date = _date_text(latest.get("date"))
    current_zone = next(
        (
            zone for zone in reversed(zones)
            if zone["start_date"] <= latest_date <= zone["end_date"]
        ),
        None,
    )
    macd = _macd(rows)
    rsi = _rsi(rows)
    kdj = _kdj(rows)
    demark = _demark(rows)
    cbsp_points = _strict_cbsp_points(bis, zones, macd, rows)
    channel = _channel(rows)
    divergences = _divergences(bis, macd, rows)
    signals = sorted(
        [
            *macd["crosses"],
            *rsi["signals"],
            *kdj["signals"],
            *demark["signals"],
            *channel["breakouts"],
            *divergences,
            *segment_signals,
        ],
        key=lambda item: (item["date"], item["type"]),
    )[-100:]
    moving_averages = {
        f"ma{period}": _rolling_mean(rows, period)
        for period in (5, 10, 20, 30, 60, 120)
    }

    result = {
        "symbol": symbol,
        "as_of": latest_date,
        "bars": len(rows),
        "merged_bar_count": len(bars),
        "min_bars": min_bars,
        "merged_bars": [
            {
                "start_date": _date_text(rows[item.start].get("date")),
                "end_date": _date_text(rows[item.end].get("date")),
                "high": _round(item.high, 2),
                "low": _round(item.low, 2),
            }
            for item in bars[-120:]
        ],
        "fractals": [
            {
                "date": _date_text(rows[bars[item.index].start].get("date")),
                "price": _round(item.price, 2),
                "type": "top" if item.kind == "top" else "bottom",
                "label": "顶分型" if item.kind == "top" else "底分型",
                "confirmed": True,
            }
            for item in fractals[-80:]
        ],
        "bis": [_bi_payload(item, rows) for item in bis[-60:]],
        "segments": segments[-30:],
        "zones": zones[-20:],
        "points": points[-30:],
        "cbsp_points": cbsp_points,
        "eigen": _eigen_sequences(bis),
        "trendlines": _trendlines(fractals),
        "moving_averages": moving_averages,
        "macd": macd,
        "rsi": rsi,
        "kdj": kdj,
        "demark": demark,
        "channel": channel,
        "divergences": divergences,
        "segment_signals": segment_signals,
        "segment_zones": segment_zones,
        "signals": signals,
        "timeframes": list(requested_timeframes),
        "multi_level": {},
        "interval_nesting": [],
        "current": {
            "date": latest_date,
            "close": _round(_finite(latest.get("close")), 2),
            "zone": current_zone,
            "last_bi": _bi_payload(bis[-1], rows) if bis else None,
            "last_point": points[-1] if points else None,
            "last_cbsp": cbsp_points[-1] if cbsp_points else None,
            "last_signal": signals[-1] if signals else None,
            "macd": {
                "dif": macd["dif"][-1] if macd["dif"] else None,
                "dea": macd["dea"][-1] if macd["dea"] else None,
                "hist": macd["hist"][-1] if macd["hist"] else None,
            },
        },
        "message": "缠论结构为研究辅助结果, CBSP 仅在结构、动能和中枢条件同时确认时输出",
    }
    multi_level: dict[str, dict[str, Any]] = {}
    for timeframe in requested_timeframes:
        if timeframe == "1d":
            continue
        resampled = _resample_rows(rows, timeframe)
        if not resampled:
            continue
        multi_level[timeframe] = analyze_chan(
            pl.DataFrame(resampled),
            symbol=symbol,
            min_bars=min_bars,
            timeframes=(),
        )
    result["multi_level"] = multi_level
    result["interval_nesting"] = _interval_nesting(cbsp_points, multi_level)
    return result
