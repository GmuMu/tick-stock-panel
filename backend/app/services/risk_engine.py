"""Fail-closed paper-trading risk contract and default A-share rules."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.market_time import market_session
from app.price_limits import price_limit_pct

RISK_CONTRACT_VERSION = "1.0"
RISK_RULES_VERSION = "cn_a_share_paper_2026_09_v1"


@dataclass(frozen=True)
class RiskDecision:
    status: str
    passed: bool
    reasons: tuple[dict[str, Any], ...]
    snapshot: dict[str, Any]
    contract_version: str = RISK_CONTRACT_VERSION
    rules_version: str = RISK_RULES_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "passed": self.passed,
            "reasons": list(self.reasons),
            "snapshot": dict(self.snapshot),
            "contract_version": self.contract_version,
            "rules_version": self.rules_version,
        }


def _reason(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def evaluate_paper_order(
    *,
    plan: dict[str, Any],
    gate: dict[str, Any] | None,
    snapshot: dict[str, Any],
    existing_position: dict[str, Any] | None = None,
) -> RiskDecision:
    """Evaluate one paper order without network access or broker side effects."""
    reasons: list[dict[str, Any]] = []
    symbol = str(plan.get("symbol") or "").upper()
    side = str(plan.get("direction") or "").lower()
    entry = plan.get("entry_price")
    quantity = plan.get("quantity")
    quote = snapshot.get("quote") if isinstance(snapshot.get("quote"), dict) else {}
    quality = snapshot.get("data_quality") if isinstance(snapshot.get("data_quality"), dict) else {}
    as_of = str(snapshot.get("as_of") or plan.get("valid_from") or "")
    trade_date = _parse_date(as_of)
    session = snapshot.get("market_session") if isinstance(snapshot.get("market_session"), dict) else None

    if gate is None or gate.get("status") != "approved":
        reasons.append(_reason("decision_not_approved", "Decision Gate 未批准"))
    if plan.get("status") not in {"active", "draft"}:
        reasons.append(_reason("plan_not_executable", "交易计划不是可执行状态"))
    if not symbol:
        reasons.append(_reason("symbol_missing", "缺少标的"))
    if side not in {"buy", "sell"}:
        reasons.append(_reason("side_invalid", "仅允许 buy 或 sell"))
    if entry is None or not _finite_positive(entry):
        reasons.append(_reason("entry_invalid", "入场价必须为正数"))
    if quantity is None or not _finite_positive(quantity):
        reasons.append(_reason("quantity_invalid", "数量必须为正数"))
    elif symbol.endswith((".SH", ".SZ", ".BJ")) and not float(quantity).is_integer():
        reasons.append(_reason("quantity_not_integer", "A 股数量必须为整数"))
    elif symbol.endswith((".SH", ".SZ", ".BJ")) and side == "buy" and int(quantity) % 100 != 0:
        reasons.append(_reason("quantity_lot_invalid", "A 股买入数量必须是 100 股整数倍"))
    position_pct = plan.get("position_pct")
    if position_pct is None or not _finite(position_pct) or not 0 < float(position_pct) <= 30:
        reasons.append(_reason("position_pct_exceeded", "仓位必须大于 0 且不超过默认单标的 30%"))
    if not quality.get("usable") or quality.get("status") != "FRESH":
        reasons.append(_reason("data_quality_not_fresh", "行情数据质量不是 FRESH, 风控拒绝执行"))
    if quote.get("last_price") is None or not _finite_positive(quote.get("last_price")):
        reasons.append(_reason("quote_missing", "缺少有效最新价"))
    if session is None:
        session = market_session(trading_day=True).to_dict()
    if session.get("trading_day") is False or session.get("is_continuous") is not True:
        reasons.append(_reason("market_not_continuous", "当前不在 A 股连续竞价时段"))
    valid_until = plan.get("valid_until")
    if valid_until and as_of and str(as_of) > str(valid_until):
        reasons.append(_reason("plan_expired", "交易计划已过有效期"))

    stop = plan.get("stop_price")
    target = plan.get("target_price")
    if _finite_positive(entry) and side == "buy":
        if stop is not None and (not _finite_positive(stop) or float(stop) >= float(entry)):
            reasons.append(_reason("stop_relation_invalid", "买入计划止损价必须低于入场价"))
        if target is not None and (not _finite_positive(target) or float(target) <= float(entry)):
            reasons.append(_reason("target_relation_invalid", "买入计划目标价必须高于入场价"))
    if _finite_positive(entry) and side == "sell":
        if stop is not None and (not _finite_positive(stop) or float(stop) <= float(entry)):
            reasons.append(_reason("stop_relation_invalid", "卖出计划止损价必须高于入场价"))
        if target is not None and (not _finite_positive(target) or float(target) >= float(entry)):
            reasons.append(_reason("target_relation_invalid", "卖出计划目标价必须低于入场价"))

    prev_close = quote.get("prev_close")
    if symbol and trade_date and _finite_positive(entry) and _finite_positive(prev_close):
        limit = price_limit_pct(symbol, trade_date, is_risk_warning=bool(quote.get("is_risk_warning")))
        up = round(float(prev_close) * (1 + limit) + 1e-8, 2)
        down = round(float(prev_close) * (1 - limit) + 1e-8, 2)
        if side == "buy" and float(entry) >= up:
            reasons.append(_reason("limit_up_unavailable", "买入价触及涨停, 纸面规则按不可成交处理"))
        if side == "sell" and float(entry) <= down:
            reasons.append(_reason("limit_down_unavailable", "卖出价触及跌停, 纸面规则按不可成交处理"))

    account_equity = snapshot.get("account_equity")
    max_exposure_pct = snapshot.get("max_exposure_pct", 100)
    current_value = float((existing_position or {}).get("quantity") or 0) * float((existing_position or {}).get("avg_cost") or 0)
    requested_value = float(entry or 0) * float(quantity or 0)
    if (
        _finite_positive(account_equity)
        and _finite(max_exposure_pct)
        and (current_value + requested_value) / float(account_equity) * 100 > float(max_exposure_pct)
    ):
        reasons.append(_reason("exposure_exceeded", "总暴露超过配置上限"))
    if side == "sell" and existing_position and float(quantity or 0) > float(existing_position.get("available_quantity") or 0):
        reasons.append(_reason("position_unavailable", "可卖持仓不足, A 股 T+1 规则拒绝卖出"))

    return RiskDecision(
        status="passed" if not reasons else "rejected",
        passed=not reasons,
        reasons=tuple(reasons),
        snapshot={
            "symbol": symbol,
            "side": side,
            "entry_price": entry,
            "quantity": quantity,
            "as_of": as_of,
            "market_session": session,
            "data_quality": quality,
            "quote": quote,
            "contract_version": RISK_CONTRACT_VERSION,
            "rules_version": RISK_RULES_VERSION,
        },
    )


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _finite_positive(value: Any) -> bool:
    return _finite(value) and float(value) > 0


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None
