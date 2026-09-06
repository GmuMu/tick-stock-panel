"""Safe backup and restore helpers for the runtime data directory.

Backups are self-describing ZIP archives with a manifest and SHA-256 checksums.
Restore is intentionally explicit: validation is the default, while replacing
the data directory requires ``confirm=True`` and keeps the pre-restore tree.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKUP_SCHEMA_VERSION = 1
MANIFEST_NAME = ".tickflow-manifest.json"


class BackupError(RuntimeError):
    """Raised when a backup cannot be safely created, checked, or restored."""


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(member: str) -> str:
    normalized = member.replace("\\", "/")
    path = Path(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise BackupError(f"unsafe archive member: {member}")
    return normalized


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _manifest_for(archive: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(archive) as handle:
            raw = json.loads(handle.read(MANIFEST_NAME).decode("utf-8"))
    except (OSError, KeyError, ValueError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise BackupError(f"invalid backup archive: {archive}") from exc
    if raw.get("schema_version") != BACKUP_SCHEMA_VERSION:
        raise BackupError("unsupported backup schema")
    if not isinstance(raw.get("files"), list):
        raise BackupError("backup manifest has no file list")
    return raw


def _backup_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "user_data" / "backups"


def create_backup(data_dir: Path, *, label: str = "manual") -> dict[str, Any]:
    """Create an atomic, content-addressed backup archive."""
    data_dir = Path(data_dir).resolve()
    if not data_dir.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
    if not data_dir.is_dir():
        raise BackupError(f"data directory is not a directory: {data_dir}")

    destination_dir = _backup_dir(data_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    filename = f"tickflow-{label}-{_stamp()}-{uuid.uuid4().hex[:8]}.zip"
    destination = destination_dir / filename
    fd, temp_name = tempfile.mkstemp(prefix=f".{filename}.", suffix=".tmp", dir=destination_dir)
    os.close(fd)
    temp_path = Path(temp_name)
    files: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(data_dir.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                if _inside(path, destination_dir):
                    continue
                relative = path.relative_to(data_dir).as_posix()
                files.append({
                    "path": relative,
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                })
                archive.write(path, relative)
            manifest = {
                "schema_version": BACKUP_SCHEMA_VERSION,
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "label": label,
                "file_count": len(files),
                "files": files,
            }
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(temp_path, destination)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return {
        "path": str(destination),
        "filename": destination.name,
        "size": destination.stat().st_size,
        "manifest": manifest,
    }


def validate_backup(archive: Path) -> dict[str, Any]:
    """Validate archive structure and every manifest checksum without extraction."""
    archive = Path(archive).resolve()
    manifest = _manifest_for(archive)
    expected = {item["path"]: item for item in manifest["files"]}
    try:
        with zipfile.ZipFile(archive) as handle:
            names = set(handle.namelist())
            if MANIFEST_NAME not in names:
                raise BackupError("backup manifest is missing")
            for name in names - {MANIFEST_NAME}:
                _safe_relative(name)
            if set(expected) != names - {MANIFEST_NAME}:
                raise BackupError("backup manifest does not match archive members")
            for name, item in expected.items():
                if not isinstance(item, dict) or item.get("sha256") is None:
                    raise BackupError(f"invalid checksum entry: {name}")
                digest = hashlib.sha256(handle.read(name)).hexdigest()
                if digest != item["sha256"]:
                    raise BackupError(f"checksum mismatch: {name}")
    except (OSError, zipfile.BadZipFile) as exc:
        raise BackupError(f"unable to read backup archive: {archive}") from exc
    return {
        "valid": True,
        "path": str(archive),
        "filename": archive.name,
        "size": archive.stat().st_size,
        "manifest": manifest,
    }


def list_backups(data_dir: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    """Return newest valid/invalid backup metadata without exposing contents."""
    directory = _backup_dir(Path(data_dir))
    if not directory.exists():
        return []
    result: list[dict[str, Any]] = []
    for archive in sorted(directory.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            item = validate_backup(archive)
            manifest = item["manifest"]
            result.append({
                "filename": archive.name,
                "size": item["size"],
                "created_at": manifest.get("created_at"),
                "label": manifest.get("label"),
                "file_count": manifest.get("file_count", 0),
                "valid": True,
            })
        except BackupError as exc:
            result.append({"filename": archive.name, "valid": False, "error": str(exc)})
        if len(result) >= limit:
            break
    return result


def restore_backup(
    data_dir: Path,
    archive: Path,
    *,
    confirm: bool = False,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Validate and optionally replace the complete data directory.

    The old data tree is renamed to a sibling ``*.pre-restore-*`` directory,
    which provides a local rollback point if the application fails to start.
    """
    data_dir = Path(data_dir).resolve()
    archive = Path(archive).resolve()
    checked = validate_backup(archive)
    if dry_run or not confirm:
        return {"restored": False, "dry_run": True, **checked}

    if not _inside(archive, _backup_dir(data_dir)):
        raise BackupError("restore archive must be inside the configured backup directory")
    staging = Path(tempfile.mkdtemp(prefix=f".{data_dir.name}.restore-", dir=data_dir.parent))
    previous: Path | None = None
    try:
        with zipfile.ZipFile(archive) as handle:
            for name in handle.namelist():
                if name == MANIFEST_NAME:
                    continue
                relative = _safe_relative(name)
                target = (staging / relative).resolve()
                if not _inside(target, staging):
                    raise BackupError(f"unsafe restore target: {name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with handle.open(name) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
        stamp = _stamp()
        previous = data_dir.with_name(f"{data_dir.name}.pre-restore-{stamp}")
        if previous.exists():
            raise BackupError(f"rollback directory already exists: {previous}")
        if data_dir.exists():
            data_dir.rename(previous)
        try:
            staging.rename(data_dir)
        except Exception:
            if previous and previous.exists() and not data_dir.exists():
                previous.rename(data_dir)
            raise
        return {
            "restored": True,
            "dry_run": False,
            "archive": archive.name,
            "rollback_dir": str(previous) if previous else None,
            "manifest": checked["manifest"],
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
