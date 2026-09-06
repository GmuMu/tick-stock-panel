"""Authenticated operational endpoints for backup, metrics, and security."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import secrets_store
from app.observability import metrics
from app.services.backup import BackupError, create_backup, list_backups

router = APIRouter(prefix="/api/ops", tags=["operations"])


def _data_dir(request: Request) -> Path:
    repo = getattr(request.app.state, "repo", None)
    if repo is not None:
        return Path(repo.store.data_dir)
    return Path(request.app.state.data_dir)


class BackupCreateIn(BaseModel):
    label: str = Field(default="manual", min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")


class SecretRotateIn(BaseModel):
    field: str = Field(min_length=3, max_length=100, pattern=r"^[a-z0-9_]+$")
    value: str = Field(min_length=1, max_length=4096)


@router.get("/metrics")
def get_metrics() -> dict[str, Any]:
    return metrics.snapshot()


@router.get("/backups")
def backups(request: Request) -> dict[str, Any]:
    return {"items": list_backups(_data_dir(request))}


@router.post("/backups")
def backup(request: Request, body: BackupCreateIn) -> dict[str, Any]:
    try:
        return create_backup(_data_dir(request), label=body.label)
    except BackupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/security/secrets")
def secret_metadata() -> dict[str, Any]:
    return {"items": secrets_store.list_metadata()}


@router.post("/security/secrets/rotate")
def rotate_secret(body: SecretRotateIn) -> dict[str, Any]:
    if not secrets_store.is_rotatable_field(body.field):
        raise HTTPException(status_code=400, detail="field is not a supported secret field")
    return {"ok": True, "item": secrets_store.rotate(body.field, body.value)}
