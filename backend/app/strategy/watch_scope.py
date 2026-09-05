"""Versioned watch-scope resolution for monitor rules.

The monitor engine consumes a small immutable snapshot instead of interpreting
scope fields independently.  Dynamic watchlist groups are resolved through the
watchlist service revision, so membership changes are observable without
scanning the files on every evaluation.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from typing import Any, Literal

WATCH_SCOPE_CONTRACT_VERSION = "1.0"
WATCH_SCOPE_KINDS = frozenset({"all", "symbols", "watchlist_group"})
WATCH_SCOPE_STATUSES = frozenset({"active", "empty", "invalid"})

ScopeStatus = Literal["active", "empty", "invalid"]

_group_cache_lock = threading.Lock()
_group_cache: dict[str, tuple[int, dict[str, frozenset[str]]]] = {}


@dataclass(frozen=True)
class WatchScope:
    """Serializable scope snapshot used by rule evaluation and alert events."""

    contract_version: str
    scope_version: str
    scope: str
    asset_type: str
    rule_id: str | None
    symbols: tuple[str, ...]
    group_id: str | None
    source: str
    source_revision: int | None
    status: ScopeStatus
    reason_code: str | None

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["symbols"] = list(self.symbols)
        return result


def _snapshot_version(
    *,
    scope: str,
    asset_type: str,
    rule_id: str | None,
    symbols: tuple[str, ...],
    group_id: str | None,
    source: str,
    source_revision: int | None,
    status: ScopeStatus,
    reason_code: str | None,
) -> str:
    payload = {
        "contract_version": WATCH_SCOPE_CONTRACT_VERSION,
        "scope": scope,
        "asset_type": asset_type,
        "rule_id": rule_id,
        "symbols": list(symbols),
        "group_id": group_id,
        "source": source,
        "source_revision": source_revision,
        "status": status,
        "reason_code": reason_code,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"{WATCH_SCOPE_CONTRACT_VERSION}:{digest}"


def _build_scope(
    rule: dict,
    *,
    scope: str,
    asset_type: str,
    symbols: tuple[str, ...] = (),
    group_id: str | None = None,
    source: str,
    source_revision: int | None = None,
    status: ScopeStatus = "active",
    reason_code: str | None = None,
) -> WatchScope:
    rule_id = str(rule.get("id")) if rule.get("id") is not None else None
    return WatchScope(
        contract_version=WATCH_SCOPE_CONTRACT_VERSION,
        scope_version=_snapshot_version(
            scope=scope,
            asset_type=asset_type,
            rule_id=rule_id,
            symbols=symbols,
            group_id=group_id,
            source=source,
            source_revision=source_revision,
            status=status,
            reason_code=reason_code,
        ),
        scope=scope,
        asset_type=asset_type,
        rule_id=rule_id,
        symbols=symbols,
        group_id=group_id,
        source=source,
        source_revision=source_revision,
        status=status,
        reason_code=reason_code,
    )


def _watchlist_groups_snapshot() -> tuple[int, dict[str, frozenset[str]]]:
    """Return the current group membership snapshot and service revision."""
    from app.config import settings
    from app.services import watchlist

    data_key = str(settings.data_dir.resolve())
    revision = int(watchlist.revision())
    with _group_cache_lock:
        cached = _group_cache.get(data_key)
        if cached is not None and cached[0] == revision:
            return cached

    groups: dict[str, set[str]] = {
        str(group["id"]): set() for group in watchlist.list_groups()
    }
    for row in watchlist.list_symbols():
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        for group_id in row.get("group_ids") or []:
            members = groups.get(str(group_id))
            if members is not None:
                members.add(symbol)

    frozen = {group_id: frozenset(members) for group_id, members in groups.items()}
    if int(watchlist.revision()) == revision:
        with _group_cache_lock:
            _group_cache[data_key] = (revision, frozen)
    return revision, frozen


def resolve_watch_scope(rule: dict) -> WatchScope:
    """Resolve one rule into a versioned, fail-closed scope snapshot.

    ``all`` is an unbounded market scope, ``symbols`` is a canonical static
    symbol set, and ``watchlist_group`` is a dynamic set tied to the
    watchlist service revision.  Empty or unavailable dynamic scopes never
    degrade to ``all``.
    """
    scope = str(rule.get("scope") or "symbols")
    asset_type = str(rule.get("asset_type") or "stock")

    if scope == "all":
        return _build_scope(
            rule,
            scope=scope,
            asset_type=asset_type,
            source="market_universe",
        )

    if scope == "symbols":
        symbols = tuple(sorted({
            str(symbol).strip()
            for symbol in rule.get("symbols") or []
            if str(symbol).strip()
        }))
        if not symbols:
            return _build_scope(
                rule,
                scope=scope,
                asset_type=asset_type,
                source="rule",
                status="invalid",
                reason_code="EMPTY_SYMBOLS",
            )
        return _build_scope(
            rule,
            scope=scope,
            asset_type=asset_type,
            symbols=symbols,
            source="rule",
        )

    if scope == "watchlist_group":
        group_id = str(rule.get("group_id") or "").strip() or None
        if group_id is None:
            return _build_scope(
                rule,
                scope=scope,
                asset_type=asset_type,
                source="watchlist",
                status="invalid",
                reason_code="MISSING_GROUP_ID",
            )
        try:
            revision, groups = _watchlist_groups_snapshot()
        except Exception:
            return _build_scope(
                rule,
                scope=scope,
                asset_type=asset_type,
                group_id=group_id,
                source="watchlist",
                status="invalid",
                reason_code="GROUP_SOURCE_ERROR",
            )
        if group_id not in groups:
            return _build_scope(
                rule,
                scope=scope,
                asset_type=asset_type,
                group_id=group_id,
                source="watchlist",
                source_revision=revision,
                status="invalid",
                reason_code="GROUP_NOT_FOUND",
            )
        symbols = tuple(sorted(groups[group_id]))
        return _build_scope(
            rule,
            scope=scope,
            asset_type=asset_type,
            symbols=symbols,
            group_id=group_id,
            source="watchlist",
            source_revision=revision,
            status="active" if symbols else "empty",
            reason_code=None if symbols else "EMPTY_GROUP",
        )

    return _build_scope(
        rule,
        scope=scope,
        asset_type=asset_type,
        source="rule",
        status="invalid",
        reason_code="UNSUPPORTED_SCOPE",
    )
