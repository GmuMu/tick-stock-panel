"""市场情绪周期阶段(冰点/启动/主升/高潮/退潮/修复) — 纯函数模块。

与 regime_builder 的 5 档 state(强势/偏强/震荡/偏弱/弱势)并存:
- state: 综合情绪分(赚钱/投机/抗跌/趋势 4 维加权), 回测环境过滤与挖掘在用, 不动。
- phase: 基于"连板梯队"的阶段(用户判据: 高度、宽度、晋级率、梯队完整度),
  刻画情绪周期位置(冰点→启动→主升→高潮→退潮), 供市场环境页分析与主线识别。

驱动量(全部可从已存储的 consecutive_limit_ups 派生, 2020-08 起全历史可回算):
- height 高度: 当日最高连板数
- first_board 首板宽度: 首板(1 连板)家数
- ge2/ge3/ge5 宽度: N 板以上家数
- promo 晋级率: 昨日连板池今日继续封板的比例 (池 <10 家记 null)
- seal_rate 封板率: regime 已有列
- ladder_completeness 梯队完整度: 2..height 档位中非空占比

阈值标定: 2020-08~2026-08 全市场 1454 个交易日的 p10/p60/p90 分位数
(标定脚本一次性运行, 不提交); 关键异常段抽查(2024-09/10 rally→climax→ebb,
2024-01/02 微盘退潮)人工核过归属。阈值集中在下方, 调整只需改这里。
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)

PHASE_CONTRACT_VERSION = "1.0"

# ───────────────────────── 阶段词汇 ─────────────────────────
PHASE_ICE = "ice"
PHASE_IGNITE = "ignite"
PHASE_RALLY = "rally"
PHASE_CLIMAX = "climax"
PHASE_EBB = "ebb"
PHASE_REPAIR = "repair"

PHASE_LABELS = {
    PHASE_ICE: "冰点",
    PHASE_IGNITE: "启动",
    PHASE_RALLY: "主升",
    PHASE_CLIMAX: "高潮",
    PHASE_EBB: "退潮",
    PHASE_REPAIR: "修复",
}

# 规则判定优先级: 高潮 > 主升 > 退潮 > 启动 > 冰点 > 修复(兜底)
_PHASE_PRIORITY = (PHASE_CLIMAX, PHASE_RALLY, PHASE_EBB, PHASE_IGNITE, PHASE_ICE)

# ───────────────────────── 阈值(标定自 2020-08~2026-08 分位数) ─────────────────────────
# 高潮: 情绪极端宣泄 — 二板以上宽度或首板数达到 p90 的 ~2 倍以上(历史 <2% 天数)
CLIMAX_GE2 = 50            # p90(25) 的 2 倍
CLIMAX_FIRST_BOARD = 220   # p90(88) 的 2.5 倍
# 主升: 高度/宽度/晋级率同时高于中位 (p60), 或晋级率极强 (p85+)
RALLY_HEIGHT = 7           # p60
RALLY_GE2 = 15             # p60
RALLY_PROMO = 0.23         # p60
RALLY_PROMO_ALT = 0.30     # p85+
RALLY_GE2_ALT = 12
RALLY_HEIGHT_ALT = 5
# 退潮: 晋级率崩至 p20 以下且宽度自近期高位回落; 或晋级率/封板率双弱
EBB_PROMO = 0.15           # p20
EBB_PROMO_STRICT = 0.13
EBB_SEAL = 0.57            # ~p10-p15
EBB_RECENT_GE2 = 12        # 5 日前 ge2 高于此才认定"自高位退潮"
EBB_RECENT_HEIGHT = 6
# 启动: 宽度/高度自低位扩张且晋级率恢复
IGNITE_GE2_DELTA = 3       # ge2 较 5 日前增加量
IGNITE_GE2 = 8             # p20-p40
IGNITE_PROMO = 0.20        # ~p55
IGNITE_HEIGHT_DELTA = 1    # height 较 5 日前抬升
IGNITE_HEIGHT = 5          # p40
IGNITE_PROMO_SOFT = 0.19
# 冰点: 高度/宽度/首板同时贴地 (p10)
ICE_HEIGHT = 4             # p10-p20
ICE_GE2 = 6                # p10
ICE_FIRST_BOARD = 24       # p10

# 晋级率最小池(家数), 低于此记 null(小样本噪声)
PROMO_MIN_POOL = 10
# 平滑与持续性: EMA alpha≈1/3 (约 5 日), 阶段切换需连续 CONFIRM_DAYS 日同标签
_EMA_ALPHA = 1.0 / 3.0
_CONFIRM_DAYS = 2
# 大盘弱档否决: 正面阶段(主升/高潮/启动)不允许出现在 5 档 state 为弱势/偏弱的日子。
# 涨停梯队可能与大盘背离(如 2024-01 微盘崩期间中字头涨停生态走强), 该否决
# 保证"主升"标签在大盘层面也成立; state 列缺失时(单元测试)不启用否决。
_POSITIVE_PHASES = frozenset({PHASE_CLIMAX, PHASE_RALLY, PHASE_IGNITE})
_VETO_STATES = frozenset({"weak", "lean_weak"})


@dataclass(frozen=True)
class PhaseSmoothingState:
    """可跨批次/跨日恢复的阶段平滑状态。"""

    contract_version: str
    last_date: str | None
    current_phase: str | None
    pending_phase: str | None
    pending_days: int
    ema_height: float | None
    ema_first_board: float | None
    ema_ge2: float | None
    ema_promo: float | None
    ema_seal: float | None
    first_height: float | None
    first_ge2: float | None
    recent_height: tuple[float, ...]
    recent_ge2: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["recent_height"] = list(self.recent_height)
        result["recent_ge2"] = list(self.recent_ge2)
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PhaseSmoothingState:
        """从 JSON 兼容地恢复状态, 非法/缺失字段由调用方拒绝。"""
        return cls(
            contract_version=str(value.get("contract_version", PHASE_CONTRACT_VERSION)),
            last_date=value.get("last_date"),
            current_phase=value.get("current_phase"),
            pending_phase=value.get("pending_phase"),
            pending_days=max(0, int(value.get("pending_days", 0))),
            ema_height=_optional_float(value.get("ema_height")),
            ema_first_board=_optional_float(value.get("ema_first_board")),
            ema_ge2=_optional_float(value.get("ema_ge2")),
            ema_promo=_optional_float(value.get("ema_promo")),
            ema_seal=_optional_float(value.get("ema_seal")),
            first_height=_optional_float(value.get("first_height")),
            first_ge2=_optional_float(value.get("first_ge2")),
            recent_height=_float_tuple(value.get("recent_height")),
            recent_ge2=_float_tuple(value.get("recent_ge2")),
        )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result


def _float_tuple(value: Any) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(result for item in value if (result := _optional_float(item)) is not None)[-5:]


def with_prev_consecutive(df: pl.DataFrame) -> pl.DataFrame:
    """按 symbol 追加昨日连板数列 _prev_consec (供晋级率)。

    df 需含 symbol/date/consecutive_limit_ups; 输入应覆盖前一交易日
    (调用方保证 warmup 或直接传全量), 每个符号首行 _prev_consec 为 null。
    """
    if "_prev_consec" in df.columns:
        return df
    return (
        df.sort(["symbol", "date"])
        .with_columns(
            pl.col("consecutive_limit_ups").shift(1).over("symbol").alias("_prev_consec")
        )
    )


def ladder_daily_aggs() -> list[pl.Expr]:
    """group_by("date").agg(...) 可直接拼接的梯队聚合表达式。

    要求 df 含 consecutive_limit_ups; 含 _prev_consec 时附带晋级率分子/分母。
    """
    consec = pl.col("consecutive_limit_ups")
    exprs = [
        consec.eq(1).sum().alias("first_board"),
        consec.ge(2).sum().alias("ge2_count"),
        consec.ge(3).sum().alias("ge3_count"),
        consec.ge(5).sum().alias("ge5_count"),
        consec.filter(consec.ge(2)).n_unique().alias("rungs_filled"),
    ]
    return exprs


def ladder_promo_aggs() -> list[pl.Expr]:
    """晋级率聚合(分子/分母); 要求 df 已含 _prev_consec 列。"""
    prev = pl.col("_prev_consec")
    consec = pl.col("consecutive_limit_ups")
    return [
        prev.ge(1).sum().alias("promo_pool"),
        (prev.ge(1) & consec.eq(prev + 1)).sum().alias("promo_ok"),
    ]


def finalize_ladder_row(r: dict) -> dict:
    """把聚合行的梯队原始值整理为持久化字段(晋级率/ladder_completeness)。"""
    height = int(r.get("max_consecutive") or 0)
    rungs = int(r.get("rungs_filled") or 0)
    completeness = (rungs / (height - 1)) if height >= 3 else 0.0
    pool = int(r.get("promo_pool") or 0)
    ok = int(r.get("promo_ok") or 0)
    promo = (ok / pool) if pool >= PROMO_MIN_POOL else None
    return {
        "first_board": int(r.get("first_board") or 0),
        "ge2_count": int(r.get("ge2_count") or 0),
        "ge3_count": int(r.get("ge3_count") or 0),
        "ge5_count": int(r.get("ge5_count") or 0),
        "ladder_completeness": round(completeness, 4),
        "promo_pool": pool,
        "promo_rate": round(promo, 4) if promo is not None else None,
    }


def _ema(values: list[float], alpha: float = _EMA_ALPHA) -> list[float]:
    out: list[float] = []
    cur = None
    for v in values:
        if v is None or v != v:  # None 或 NaN
            if cur is None:
                out.append(None)
                continue
            out.append(cur)  # ffill: 缺失沿用上一平滑值
            continue
        cur = v if cur is None else cur + alpha * (v - cur)
        out.append(cur)
    # 前向回填: 序列开头缺失用首个有效值
    first_valid = next((i for i, x in enumerate(out) if x is not None), None)
    if first_valid is not None:
        for i in range(first_valid):
            out[i] = out[first_valid]
    else:
        out = [0.0] * len(values)
    return out


def _ema_step(previous: float | None, value: float | None, seed: float) -> float:
    value = value if value is not None else seed
    if previous is None:
        return value
    return previous + _EMA_ALPHA * (value - previous)


def _classify_raw_phase(
    *,
    height: float,
    first_board: float,
    ge2: float,
    promo: float,
    seal: float,
    previous_ge2: float,
    previous_height: float,
) -> str:
    """按当前平滑值输出未确认的阶段标签。"""
    if ge2 >= CLIMAX_GE2 or first_board >= CLIMAX_FIRST_BOARD:
        return PHASE_CLIMAX
    if height >= RALLY_HEIGHT and ge2 >= RALLY_GE2 and promo >= RALLY_PROMO:
        return PHASE_RALLY
    if promo >= RALLY_PROMO_ALT and ge2 >= RALLY_GE2_ALT and height >= RALLY_HEIGHT_ALT:
        return PHASE_RALLY
    if height <= ICE_HEIGHT and ge2 <= ICE_GE2 and first_board <= ICE_FIRST_BOARD:
        return PHASE_ICE
    from_high = previous_ge2 >= EBB_RECENT_GE2 or previous_height >= EBB_RECENT_HEIGHT
    if from_high and (promo <= EBB_PROMO and ge2 < previous_ge2):
        return PHASE_EBB
    if promo <= EBB_PROMO_STRICT and seal <= EBB_SEAL:
        return PHASE_EBB
    if ge2 - previous_ge2 >= IGNITE_GE2_DELTA and ge2 >= IGNITE_GE2 and promo >= IGNITE_PROMO:
        return PHASE_IGNITE
    if (
        height - previous_height >= IGNITE_HEIGHT_DELTA
        and height >= IGNITE_HEIGHT
        and promo >= IGNITE_PROMO_SOFT
    ):
        return PHASE_IGNITE
    return PHASE_REPAIR


def advance_phase_state(
    previous: PhaseSmoothingState | None,
    *,
    date_value: str,
    height: float | None,
    first_board: float | None,
    ge2: float | None,
    promo: float | None,
    seal: float | None,
    state: str | None = None,
) -> tuple[str, PhaseSmoothingState]:
    """推进一天的阶段状态并返回当天标签与新状态。"""
    if previous is not None and previous.last_date is not None and date_value <= previous.last_date:
        raise ValueError(f"phase 日期必须递增: {date_value} <= {previous.last_date}")

    seed_height = height if height is not None else (previous.ema_height if previous else 0.0) or 0.0
    seed_first = (
        first_board
        if first_board is not None
        else (previous.ema_first_board if previous else 0.0) or 0.0
    )
    seed_ge2 = ge2 if ge2 is not None else (previous.ema_ge2 if previous else 0.0) or 0.0
    seed_promo = promo if promo is not None else (previous.ema_promo if previous else 0.0) or 0.0
    seed_seal = seal if seal is not None else (previous.ema_seal if previous else 0.0) or 0.0

    ema_height = _ema_step(previous.ema_height if previous else None, height, seed_height)
    ema_first = _ema_step(previous.ema_first_board if previous else None, first_board, seed_first)
    ema_ge2 = _ema_step(previous.ema_ge2 if previous else None, ge2, seed_ge2)
    ema_promo = _ema_step(previous.ema_promo if previous else None, promo, seed_promo)
    ema_seal = _ema_step(previous.ema_seal if previous else None, seal, seed_seal)

    if previous is None:
        previous_ge2 = ema_ge2
        previous_height = ema_height
        first_height = ema_height
        first_ge2 = ema_ge2
        recent_height: tuple[float, ...] = ()
        recent_ge2: tuple[float, ...] = ()
        current_phase = None
        pending_phase = None
        pending_days = 0
    else:
        previous_ge2 = (
            previous.recent_ge2[-5]
            if len(previous.recent_ge2) >= 5
            else previous.first_ge2 if previous.first_ge2 is not None else ema_ge2
        )
        previous_height = (
            previous.recent_height[-5]
            if len(previous.recent_height) >= 5
            else previous.first_height if previous.first_height is not None else ema_height
        )
        first_height = previous.first_height if previous.first_height is not None else ema_height
        first_ge2 = previous.first_ge2 if previous.first_ge2 is not None else ema_ge2
        recent_height = previous.recent_height
        recent_ge2 = previous.recent_ge2
        current_phase = previous.current_phase
        pending_phase = previous.pending_phase
        pending_days = previous.pending_days

    raw = _classify_raw_phase(
        height=ema_height,
        first_board=ema_first,
        ge2=ema_ge2,
        promo=ema_promo,
        seal=ema_seal,
        previous_ge2=previous_ge2,
        previous_height=previous_height,
    )
    if raw in _POSITIVE_PHASES and state in _VETO_STATES:
        raw = PHASE_REPAIR

    if current_phase is None:
        current_phase = raw
        pending_phase = None
        pending_days = 0
    elif raw == current_phase:
        pending_phase = None
        pending_days = 0
    else:
        if raw == pending_phase:
            pending_days += 1
        else:
            pending_phase = raw
            pending_days = 1
        if pending_days >= _CONFIRM_DAYS:
            current_phase = raw
            pending_phase = None
            pending_days = 0

    next_state = PhaseSmoothingState(
        contract_version=PHASE_CONTRACT_VERSION,
        last_date=date_value,
        current_phase=current_phase,
        pending_phase=pending_phase,
        pending_days=pending_days,
        ema_height=ema_height,
        ema_first_board=ema_first,
        ema_ge2=ema_ge2,
        ema_promo=ema_promo,
        ema_seal=ema_seal,
        first_height=first_height,
        first_ge2=first_ge2,
        recent_height=(*recent_height, ema_height)[-5:],
        recent_ge2=(*recent_ge2, ema_ge2)[-5:],
    )
    return current_phase, next_state


def classify_phase_series_with_state(
    daily: pl.DataFrame,
    initial_state: PhaseSmoothingState | None = None,
) -> tuple[pl.DataFrame, PhaseSmoothingState | None]:
    """按日序标注阶段, 并返回可用于下一批的平滑状态。"""
    required = {"date", "max_consecutive", "first_board", "ge2_count", "promo_rate", "seal_rate"}
    missing = required - set(daily.columns)
    if missing:
        raise ValueError(f"classify_phase_series 缺少列: {sorted(missing)}")

    rows = daily.sort("date")
    seeds: dict[str, float] = {}
    for key in ("max_consecutive", "first_board", "ge2_count", "promo_rate", "seal_rate"):
        seed = next(
            (
                float(value)
                for value in rows[key].to_list()
                if value is not None and float(value) == float(value)
            ),
            0.0,
        )
        seeds[key] = seed

    current_state = initial_state
    labels: list[str] = []
    for row in rows.iter_rows(named=True):
        value = {
            key: _optional_float(row.get(key))
            for key in ("max_consecutive", "first_board", "ge2_count", "promo_rate", "seal_rate")
        }
        for key in value:
            if value[key] is None and current_state is None:
                value[key] = seeds[key]
        label, current_state = advance_phase_state(
            current_state,
            date_value=str(row["date"]),
            height=value["max_consecutive"],
            first_board=value["first_board"],
            ge2=value["ge2_count"],
            promo=value["promo_rate"],
            seal=value["seal_rate"],
            state=row.get("state"),
        )
        labels.append(label)

    labeled = rows.with_columns(pl.Series("phase", labels, dtype=pl.Utf8))
    return labeled, current_state


def classify_phase_series(daily: pl.DataFrame) -> pl.DataFrame:
    """对完整日序打阶段标签, 保持既有调用方兼容。"""
    labeled, _ = classify_phase_series_with_state(daily)
    return labeled
