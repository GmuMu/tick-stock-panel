"""能力注册表与能力路由矩阵 — 数据集维度的单一权威定义。

能力 (capability) = 一个标准化数据集 (CONTRIBUTING「数据源插件化要求」):
daily / adj_factor / realtime / minute / depth5 / financial (注册表顺序即设置页卡片顺序)。注册表集中声明每个
能力的展示元数据、路由偏好字段与 TickFlow 档位要求, 前端设置页不再各自硬编码。
depth5 目前仅 TickFlow 供 (插件数据集白名单未开放, 见 loader), 仍进矩阵是为了
可用性门控诚实: 五档不可用时连板梯队封单/看板封单缺数据应有提示。

build_capability_matrix 把注册表、插件/自定义源的能力声明 (datasets) 和当前
路由偏好合并为一个矩阵, 供设置页一次拉全。当前偏好由 API 层注入
(preferences getters 自带合法源校验), 本模块不反向依赖 services 层。

候选契约: 每个能力的 candidates 只包含「当前确实可提供该能力」的源 —
TickFlow 按当前订阅档位过滤 (日K全档位, 其余按注册表 tf_tier 门槛),
未就绪的插件/自定义源 (依赖未装/Key 未配) 放入 pending 并携带原因,
供前端置灰提示。其他页面可以把 candidates 直接当作可用提供方名单。

usable 契约: 每个能力额外给出 usable = 生效源当前能否真正提供该能力
(生效源在 candidates 中)。各页面的能力门控 (缺能力提示 → 数据源配置)
统一以 usable 为准, 而不是 TickFlow 套餐视角 — 路由到可用插件时同样可用,
路由到 TickFlow 但档位不足时同样不可用。

能力状态契约:
  - status: 面向业务门控的稳定大写枚举: USABLE / DEGRADED / UNAVAILABLE。
  - health: 当前生效源的健康状态: healthy / degraded / unavailable。
  - priority: 注册表定义的稳定业务优先级, 数字越小越重要。
健康的生效源为 USABLE, 生效源已可用但健康状态异常或当前路由不可用且
存在可切换候选时为 DEGRADED, 没有候选时为 UNAVAILABLE。
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from app.data_providers import custom as custom_sources

CapabilityStatus = Literal["USABLE", "DEGRADED", "UNAVAILABLE"]
CapabilityHealth = Literal["healthy", "degraded", "unavailable"]


class CapabilityCandidate(TypedDict):
    name: str
    display: str
    kind: Literal["builtin", "plugin", "custom"]
    available: bool
    status: str
    note: NotRequired[str | None]


class DataCapability(TypedDict):
    """Stable API view for one standard data capability."""

    id: str
    label: str
    desc: str
    field: str | None
    default: str
    priority: int
    tf_tier: str
    tf_available: bool
    usable: bool
    status: CapabilityStatus
    health: CapabilityHealth
    provider: str
    source: str
    current: str
    current_display: str
    effective: str
    effective_display: str
    candidates: list[CapabilityCandidate]
    pending: list[CapabilityCandidate]


class CapabilityMatrix(TypedDict):
    tickflow_tier: str
    capabilities: list[DataCapability]

CAPABILITY_REGISTRY: list[dict] = [
    {
        "id": "daily",
        "label": "日K",
        "desc": "历史K线与实时覆写",
        "priority": 10,
        "field": "daily_data_provider",
        "default": "tickflow",
        "tf_tier": "none",
    },
    {
        "id": "adj_factor",
        "label": "除权因子",
        "desc": "前复权计算基准",
        "priority": 30,
        "field": "adj_factor_provider",
        "default": "tickflow",
        "tf_tier": "starter",
        # 独立路由 (曾经的「跟随日K」特殊值已下线: 每个能力单独配置,
        # 复权口径一致性改由未来的一致性警示保障, 不做路由耦合)
    },
    {
        "id": "realtime",
        "label": "实时行情",
        "desc": "全市场实时快照",
        "priority": 20,
        "field": "realtime_data_provider",
        "default": "tickflow",
        "tf_tier": "starter",
    },
    {
        "id": "minute",
        "label": "分钟K",
        "desc": "分时图与分钟回测",
        "priority": 40,
        "field": "minute_data_provider",
        "default": "tickflow",
        "tf_tier": "pro",
    },
    {
        "id": "depth5",
        "label": "五档盘口",
        "desc": "连板梯队封单与盘口深度",
        "priority": 50,
        "field": "depth5_data_provider",
        "default": "tickflow",
        "tf_tier": "pro",
        # 插件契约暂未开放 depth5 数据集 (loader 白名单), 当前仅 TickFlow 供
    },
    {
        "id": "financial",
        "label": "财务数据",
        "desc": "财务指标与三大报表",
        "priority": 60,
        "field": "financial_data_provider",
        "default": "tickflow",
        "tf_tier": "expert",
    },
    {
        "id": "full_minute",
        "label": "全量分钟",
        "desc": "盘中全市场当日分钟落盘 (冷启动全天 + 标的池增量)",
        "priority": 45,
        "field": "full_minute_data_provider",
        "default": "tickflow",
        "tf_tier": "expert",
        # TickFlow 侧需 Expert 档; 插件/自定义源声明 full_minute 数据集即可提供
        # (插件实现 get_intraday_batch / 可选 get_intraday_latest, YAML 仅修复轮)
    },
]

_TICKFLOW_CANDIDATE = {
    "name": "tickflow",
    "display": "TickFlow",
    "kind": "builtin",
    "available": True,
    "status": "ok",
    "note": None,
}

# 档位排序: none 最低 (无 Key/无效 Key, 仅免费通道历史日K), 未知档按 none 处理 (fail-closed)
_TIER_RANK = {"none": -1, "free": 0, "starter": 1, "pro": 2, "expert": 3}


def _tier_base(tier: str) -> str:
    """归一化档位输入为基础名: "Pro +" -> "pro"; 空值归为 none。"""
    text = str(tier or "").strip().lower()
    if not text:
        return "none"
    return text.split()[0].split("+")[0]


def _declared_sources() -> list[dict]:
    """插件 + 自定义源 → 统一能力声明视图。未注册 (hidden/加载失败) 的源不会出现。"""
    rows: list[dict] = []
    for plugin in custom_sources.list_plugins():
        rows.append({
            "name": plugin["name"],
            "display": plugin.get("display_name") or plugin["name"],
            "datasets": set(plugin.get("datasets") or []),
            "available": bool(plugin.get("available")),
            "status": str(plugin.get("status") or ""),
            "kind": "plugin",
        })
    for source in custom_sources.list_sources():
        rows.append({
            "name": source["name"],
            "display": source.get("display_name") or source["name"],
            "datasets": set(source.get("datasets") or []),
            # 自定义源注册即已通过加载校验, 视为可用
            "available": True,
            "status": "ok",
            "kind": "custom",
        })
    return rows


def _display_of(sources: list[dict], name: str) -> str:
    if name == "tickflow":
        return "TickFlow"
    for s in sources:
        if s["name"] == name:
            return s["display"]
    return name


def _candidate_health(candidate: dict) -> str:
    """Normalize provider status into the capability health vocabulary."""
    status = str(candidate.get("status") or "").strip().lower()
    if status in {"ok", "healthy", "ready", "available"}:
        return "healthy"
    if status in {"unavailable", "down", "failed"}:
        return "unavailable"
    return "degraded"


def _observed_health(provider: str, dataset: str) -> str | None:
    """Read runtime health without making capability discovery perform I/O."""
    from app.data_providers.health import get_provider_health_registry

    return get_provider_health_registry().health_for(provider, dataset)


def _health_status(usable: bool, candidates: list[dict], effective: str) -> tuple[str, str]:
    """Return the stable capability status and current-source health.

    ``candidates`` is intentionally the already-filtered list: a provider that
    is not a usable candidate must not make a capability look healthy merely
    because another provider is available.
    """
    if usable:
        current = next(c for c in candidates if c["name"] == effective)
        health = _candidate_health(current)
        return ("USABLE" if health == "healthy" else "DEGRADED"), health
    if candidates:
        return "DEGRADED", "degraded"
    return "UNAVAILABLE", "unavailable"


def build_capability_matrix(current: dict[str, str], tickflow_tier: str = "none") -> CapabilityMatrix:
    """注册表 + 源能力声明 + 当前偏好 → 能力路由矩阵。

    current 为 {偏好字段: 当前值}, 由 API 层经 preferences getters 注入;
    getters 已把非法值 (未注册源) 回退为默认, 这里直接信任。effective
    即当前值本身 (每个能力独立路由, 无跟随/派生特殊值)。

    tickflow_tier 为 TickFlow 当前档位基础名 (none/free/starter/pro/expert),
    由 API 层从 tickflow policy 注入。当前档位不提供的能力里 TickFlow
    不进候选, 但偏好仍指向 tickflow 时以 tf_available=False 标记,
    供前端提示「档位不足」。未知档按 none 处理。
    """
    tier_base = _tier_base(tickflow_tier)
    tier_rank = _TIER_RANK.get(tier_base, -1)
    sources = _declared_sources()

    capabilities = []
    for cap in CAPABILITY_REGISTRY:
        # field=None → 不可路由能力 (仅 TickFlow 提供, 无路由偏好), 生效源恒为默认
        effective = current.get(cap["field"], cap["default"]) if cap["field"] else cap["default"]
        tf_available = tier_rank >= _TIER_RANK[cap["tf_tier"]]
        candidates: list[dict] = []
        pending: list[dict] = []
        if tf_available:
            candidates.append(dict(_TICKFLOW_CANDIDATE))
        for s in sources:
            if cap["id"] not in s["datasets"]:
                continue
            entry = {
                "name": s["name"],
                "display": s["display"],
                "kind": s["kind"],
                "available": s["available"],
                "status": s["status"],
                "note": None if s["available"] else (s["status"] or "不可用"),
            }
            observed = _observed_health(s["name"], cap["id"])
            if observed is not None:
                entry["status"] = observed
            (candidates if s["available"] else pending).append(entry)
        for candidate in candidates:
            observed = _observed_health(candidate["name"], cap["id"])
            if observed is not None:
                candidate["status"] = observed
        usable = any(c["name"] == effective for c in candidates)
        status, health = _health_status(usable, candidates, effective)
        capabilities.append({
            "id": cap["id"],
            "label": cap["label"],
            "desc": cap["desc"],
            "field": cap["field"],
            "default": cap["default"],
            "priority": cap["priority"],
            "tf_tier": cap["tf_tier"],
            "tf_available": tf_available,
            "usable": usable,
            "status": status,
            "health": health,
            "provider": effective,
            "source": _display_of(sources, effective),
            "current": effective,
            "current_display": _display_of(sources, effective),
            "effective": effective,
            "effective_display": _display_of(sources, effective),
            "candidates": candidates,
            "pending": pending,
        })
    return {"tickflow_tier": tier_base, "capabilities": capabilities}
