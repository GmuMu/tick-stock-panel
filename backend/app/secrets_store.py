"""Key / 凭据本地存储(§14)。

存储位置:`data/user_data/secrets.json`,权限 0600。
优先级:secrets.json > .env > 空(Free 模式)。

UI 改 Key 时只动这个文件,不动 .env。
"""
from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)
_METADATA_KEY = "_metadata"
_ROTATABLE_FIELD = re.compile(r"^[a-z0-9_]+(?:api_key|secret)$")


def _path() -> Path:
    from app.config import settings
    p = settings.data_dir / "user_data" / "secrets.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load() -> dict:
    p = _path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.warning("secrets.json malformed: %s", e)
    return {}


def save(updates: dict) -> dict:
    """合并写入(不会清掉未提及的字段)。返回新内容。"""
    current = load()
    metadata = current.get(_METADATA_KEY)
    if not isinstance(metadata, dict):
        metadata = {}
    current.update({k: v for k, v in updates.items() if v is not None})
    for field, value in updates.items():
        if is_rotatable_field(field) and value:
            metadata[field] = _metadata_for(str(value), metadata.get(field))
    if metadata:
        current[_METADATA_KEY] = metadata
    p = _path()
    p.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return current


def clear(*keys: str) -> dict:
    """清掉指定字段(留空清全部)。"""
    p = _path()
    if not p.exists():
        return {}
    if not keys:
        p.unlink()
        return {}
    current = load()
    for k in keys:
        current.pop(k, None)
        if isinstance(current.get(_METADATA_KEY), dict):
            current[_METADATA_KEY].pop(k, None)
    p.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    return current


def is_rotatable_field(field: str) -> bool:
    """Return whether a field is a supported secret slot, without reading it."""
    return bool(_ROTATABLE_FIELD.fullmatch(str(field)))


def _metadata_for(value: str, previous: dict | None = None) -> dict:
    old_version = int((previous or {}).get("version", 0) or 0)
    return {
        "version": old_version + 1,
        "rotated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fingerprint": hashlib.sha256(value.encode("utf-8")).hexdigest()[:16],
    }


def rotate(field: str, value: str) -> dict:
    """Replace a secret and return non-sensitive rotation metadata only."""
    if not is_rotatable_field(field):
        raise ValueError("unsupported secret field")
    value = str(value).strip()
    if not value:
        raise ValueError("secret value must not be empty")
    current = load()
    metadata = current.get(_METADATA_KEY)
    metadata = metadata if isinstance(metadata, dict) else {}
    previous = metadata.get(field)
    item = _metadata_for(value, previous)
    current[field] = value
    current[_METADATA_KEY] = metadata
    metadata[field] = item
    p = _path()
    p.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return {"field": field, **item, "masked": mask(value)}


def list_metadata() -> list[dict]:
    """List secret status without returning secret values."""
    current = load()
    saved = current.get(_METADATA_KEY)
    saved = saved if isinstance(saved, dict) else {}
    result: list[dict] = []
    for field, value in sorted(current.items()):
        if field == _METADATA_KEY or not is_rotatable_field(field):
            continue
        item = saved.get(field) if isinstance(saved.get(field), dict) else {}
        result.append({
            "field": field,
            "configured": bool(value),
            "masked": mask(str(value)),
            "version": int(item.get("version", 1)),
            "rotated_at": item.get("rotated_at"),
            "fingerprint": item.get("fingerprint"),
        })
    return result


def get_tickflow_key() -> str:
    """取当前 TickFlow Key:secrets.json 优先,否则 .env。"""
    val = load().get("tickflow_api_key")
    if val:
        return val
    from app.config import settings
    return settings.tickflow_api_key or ""


def get_ai_key() -> str:
    """取当前 AI Key:secrets.json 优先,否则 .env。"""
    val = load().get("ai_api_key")
    if val:
        return val
    from app.config import settings
    return settings.ai_api_key or ""


def get_ai_config(key: str, default: str = "") -> str:
    """取 AI 配置项:secrets.json 优先,否则 config。"""
    val = load().get(key)
    if val:
        return val
    from app.config import settings
    return getattr(settings, key, default) or default


def get_ai_config_int(key: str, default: int) -> int:
    """取 AI 数值配置项 (如 ai_max_output_tokens): secrets.json 优先,否则 config。"""
    val = load().get(key)
    if val is not None:
        try:
            return int(val)
        except (TypeError, ValueError):
            logger.warning("ai config %s is not an int: %r", key, val)
    from app.config import settings
    return int(getattr(settings, key, default) or default)


def get_env_backed_secret(field: str, env_name: str) -> str:
    """取环境变量后备的密钥(插件 API Key 等):secrets.json 优先,否则环境变量。

    与 get_tickflow_key 同优先级语义:UI 写入 secrets.json 后即覆盖 .env。
    """
    val = load().get(field)
    if val:
        return str(val).strip()
    return os.environ.get(env_name, "").strip()


def mask(key: str, prefix: int = 4, suffix: int = 4) -> str:
    """脱敏显示。"""
    if not key:
        return ""
    if len(key) <= prefix + suffix:
        return "•" * len(key)
    return f"{key[:prefix]}{'•' * 6}{key[-suffix:]}"
