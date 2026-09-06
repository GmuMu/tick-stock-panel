"""CLI for validating, backing up, and restoring Tick Stock Panel data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import settings
from app.services.backup import create_backup, list_backups, restore_backup, validate_backup


def main() -> None:
    parser = argparse.ArgumentParser(description="Tick Stock Panel data backup utility")
    parser.add_argument("--data-dir", type=Path, default=settings.data_dir)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="create an atomic ZIP backup")
    create.add_argument("--label", default="manual")

    subparsers.add_parser("list", help="list backup archives")

    validate = subparsers.add_parser("validate", help="validate one archive")
    validate.add_argument("archive", type=Path)

    restore = subparsers.add_parser("restore", help="validate or restore one archive")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--confirm", action="store_true", help="replace data directory")
    restore.add_argument("--dry-run", action="store_true", help="only validate (default)")

    args = parser.parse_args()
    if args.command == "create":
        result = create_backup(args.data_dir, label=args.label)
    elif args.command == "list":
        result = list_backups(args.data_dir)
    elif args.command == "validate":
        result = validate_backup(args.archive)
    else:
        result = restore_backup(
            args.data_dir,
            args.archive,
            confirm=args.confirm,
            dry_run=args.dry_run or not args.confirm,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
