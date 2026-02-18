"""Backup command handlers.

Purpose:
    Implement CLI command handlers for backup and restore operations.

Responsibilities:
    - Handle backup create, restore, list, verify, rotate commands
    - Call backup service layer
    - Format output as JSON

Non-scope:
    - Does not implement backup compression or encryption (handled by backup module)
    - Does not manage backup storage locations (uses settings)
    - Does not handle database connection management (abstracted in backup layer)
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace

from ..backup import create_backup, list_backups, restore_backup, rotate_backups, verify_backup
from ..settings import Settings


def backup_create_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop backup create' command."""
    result = create_backup(
        settings=settings,
        output_dir=args.output,
        name=args.name,
    )

    if result.success:
        output = {
            "success": True,
            "backup_path": str(result.backup_path),
            "manifest": result.manifest.__dict__ if result.manifest else None,
        }
        print(json.dumps(output, indent=2))
        return 0
    else:
        print(json.dumps({"success": False, "error": result.error}), file=sys.stderr)
        return 1


def backup_restore_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop backup restore' command."""
    result = restore_backup(
        settings=settings,
        backup_path=args.backup_path,
        dry_run=args.dry_run,
        force=args.force,
    )

    if result.success:
        output = {
            "success": True,
            "dry_run": result.dry_run,
            "backup_path": str(result.backup_path),
            "manifest": result.manifest.__dict__ if result.manifest else None,
            "core_restored": result.core_restored,
            "rag_restored": result.rag_restored,
        }
        print(json.dumps(output, indent=2))
        return 0
    else:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": result.error,
                    "manifest": result.manifest.__dict__ if result.manifest else None,
                }
            ),
            file=sys.stderr,
        )
        return 1


def backup_list_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop backup list' command."""
    backups = list_backups(settings=settings, limit=args.limit)

    output = [
        {
            "path": str(b.path),
            "created_at_utc": b.created_at_utc,
            "name": b.name,
            "core_schema_version": b.core_schema_version,
            "rag_schema_version": b.rag_schema_version,
            "size_bytes": b.size_bytes,
        }
        for b in backups
    ]
    print(json.dumps(output, indent=2))
    return 0


def backup_verify_command(args: Namespace, _settings: Settings) -> int:
    """Handle 'cloop backup verify' command."""
    result = verify_backup(backup_path=args.backup_path)

    output = {
        "valid": result.valid,
        "backup_path": str(result.backup_path),
        "manifest": result.manifest.__dict__ if result.manifest else None,
        "core_integrity": result.core_integrity,
        "rag_integrity": result.rag_integrity,
        "errors": result.errors,
    }
    print(json.dumps(output, indent=2))
    return 0 if result.valid else 1


def backup_rotate_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop backup rotate' command."""
    if args.dry_run:
        backups = list_backups(settings=settings)
        to_delete = backups[settings.backup_keep_count :]
        output = {
            "dry_run": True,
            "keep_count": settings.backup_keep_count,
            "total_backups": len(backups),
            "would_delete": [str(b.path) for b in to_delete],
        }
        print(json.dumps(output, indent=2))
        return 0

    deleted = rotate_backups(settings=settings)
    output = {
        "deleted": [str(d) for d in deleted],
        "count": len(deleted),
    }
    print(json.dumps(output, indent=2))
    return 0
