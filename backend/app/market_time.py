"""A股市场时间工具 — 固定北京时间 (UTC+8, 无夏令时)。

服务器/容器本地时区不可靠 (python:slim 镜像默认 UTC), 交易时段判断、
实时行情落盘日期等必须显式使用北京时间, 否则 Docker 部署时轮询窗口
与真实交易时段完全错开 (北京 9:15-15:05 = UTC 1:15-7:05)。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as dt_time
from typing import Literal

CN_TZ = timezone(timedelta(hours=8))

# A 股交易时段 (北京时间): 上午 9:30-11:30 (120 分钟) + 下午 13:00-15:00 (120 分钟) = 240 分钟
_TRADING_TOTAL_MINUTES = 240
_MORNING_START = dt_time(9, 30)
_MORNING_END = dt_time(11, 30)
_AFTERNOON_START = dt_time(13, 0)
_AFTERNOON_END = dt_time(15, 0)

MarketPhase = Literal[
    "closed",
    "preopen",
    "morning",
    "morning_final",
    "pre_afternoon",
    "afternoon",
    "close_final",
]


@dataclass(frozen=True)
class MarketSession:
    """北京时区下的一次市场时段判定。"""

    session_date: date
    phase: MarketPhase
    trading_day: bool | None
    is_continuous: bool
    is_polling_window: bool
    can_poll: bool
    elapsed_minutes: float
    reason: str

    def to_dict(self) -> dict[str, object | None]:
        """返回稳定的 API 状态结构。"""
        return {
            "date": self.session_date.isoformat(),
            "phase": self.phase,
            "trading_day": self.trading_day,
            "is_continuous": self.is_continuous,
            "is_polling_window": self.is_polling_window,
            "can_poll": self.can_poll,
            "elapsed_minutes": round(self.elapsed_minutes, 3),
            "reason": self.reason,
        }


def cn_now() -> datetime:
    """当前北京时间 (带时区)。"""
    return datetime.now(CN_TZ)


def cn_today() -> date:
    """当前北京日期。"""
    return datetime.now(CN_TZ).date()


def _as_cn_datetime(value: datetime) -> datetime:
    """将 naive 值按北京时间解释, aware 值转换到北京时间。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=CN_TZ)
    return value.astimezone(CN_TZ)


def market_session(
    now: datetime | None = None,
    *,
    trading_day: bool | None = None,
) -> MarketSession:
    """返回当前北京时区的完整市场时段结果。

    ``trading_day=None`` 时对工作日沿用旧的周几近似; 传入 False 会严格关闭
    休市日, 供交易日探针完成后的 fail-closed 消费方使用。
    """
    current = _as_cn_datetime(now or cn_now())
    weekday = current.weekday() < 5
    verdict = False if not weekday else (
        trading_day if trading_day is not None else True
    )

    if not weekday or trading_day is False:
        return MarketSession(
            session_date=current.date(),
            phase="closed",
            trading_day=verdict,
            is_continuous=False,
            is_polling_window=False,
            can_poll=False,
            elapsed_minutes=0.0,
            reason="holiday" if weekday else "weekend",
        )

    t = current.time()
    if dt_time(9, 15) <= t < dt_time(9, 30):
        phase: MarketPhase = "preopen"
        reason = "preopen"
    elif dt_time(9, 30) <= t < dt_time(11, 30):
        phase = "morning"
        reason = "continuous"
    elif dt_time(11, 30) <= t < dt_time(12, 55):
        phase = "morning_final"
        reason = "lunch_break"
    elif dt_time(12, 55) <= t < dt_time(13, 0):
        phase = "pre_afternoon"
        reason = "pre_afternoon"
    elif dt_time(13, 0) <= t < dt_time(15, 0):
        phase = "afternoon"
        reason = "continuous"
    elif t >= dt_time(15, 0):
        phase = "close_final"
        reason = "post_session"
    else:
        phase = "closed"
        reason = "pre_session"

    is_continuous = in_continuous_session(current)
    is_polling_window = phase != "closed"
    return MarketSession(
        session_date=current.date(),
        phase=phase,
        trading_day=verdict,
        is_continuous=is_continuous,
        is_polling_window=is_polling_window,
        can_poll=is_polling_window and verdict is not False,
        elapsed_minutes=trading_minutes_elapsed_from_dt(current),
        reason=reason,
    )


def in_continuous_session(now: datetime | None = None) -> bool:
    """A股连续竞价时段 (北京时间): 9:30-11:30 / 13:00-15:00, 仅工作日。"""
    now = now or cn_now()
    return now.weekday() < 5 and (
        _MORNING_START <= now.time() <= _MORNING_END
        or _AFTERNOON_START <= now.time() <= _AFTERNOON_END
    )


def trading_minutes_elapsed_from_dt(dt: datetime) -> float:
    """根据北京时间 datetime 计算当日已交易分钟数。

    交易时段: 9:30-11:30 (0~120) + 13:00-15:00 (120~240)。
    - 开盘前 = 0; 午休(11:30-13:00) = 120(保持上午累计); 收盘后 = 240。
    - 非交易日(周末) = 240 (视作全天, 避免量比被折算成 0)。
    """
    t = dt.time()
    if t < _MORNING_START:
        return 0.0
    if t < _MORNING_END:
        return (dt.hour * 60 + dt.minute - 9 * 60 - 30) + dt.second / 60.0
    if t < _AFTERNOON_START:
        return 120.0  # 午休, 保持上午累计
    if t < _AFTERNOON_END:
        return 120.0 + (dt.hour * 60 + dt.minute - 13 * 60) + dt.second / 60.0
    return float(_TRADING_TOTAL_MINUTES)


def trading_minutes_elapsed() -> float:
    """当前已交易分钟数 (基于服务端北京时间)。

    量比折算的兜底: 当行情 timestamp 缺失时用服务端时间。
    优先使用 trading_minutes_elapsed_from_ts (行情真实时间, 更准)。
    """
    return trading_minutes_elapsed_from_dt(cn_now())


def trading_minutes_elapsed_from_ts(ts_ms: int | float | None) -> float:
    """从行情时间戳(毫秒)计算当日已交易分钟数。

    优先使用此函数: 行情 timestamp 是真实成交时间, 比服务端时间更准
    (服务端时间含网络/限流延迟)。

    Args:
        ts_ms: 毫秒级 Unix 时间戳 (TickFlow SDK quote.timestamp / kline.timestamp)

    Returns:
        已交易分钟数 (0~240)。timestamp 为 None/无效时返回 240 (视作全天,
        避免量比被折算成 0)。
    """
    if not ts_ms:
        return float(_TRADING_TOTAL_MINUTES)
    try:
        dt = datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=CN_TZ)
    except (ValueError, TypeError, OSError):
        return float(_TRADING_TOTAL_MINUTES)
    return trading_minutes_elapsed_from_dt(dt)

