"""Backup command argument parsers.

Purpose:
    Argument parsers for backup and restore commands.

Responsibilities:
    - Define argument parsers for backup create, restore, list, verify, and rotate subcommands
    - Configure CLI options for backup paths, names, dry-run, and force flags
    - Provide epilog examples for each command

Non-scope:
    - Does NOT implement backup/restore logic or file operations
    - Does NOT perform archive creation or extraction
    - Does NOT handle backup rotation policies
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def add_backup_parser(subparsers: Any) -> None:
    """Add 'backup' command and subcommand parsers."""
    from argparse import RawDescriptionHelpFormatter

    backup_parser = subparsers.add_parser(
        "backup",
        help="Backup and restore commands",
        description="Manage Cloop data backups",
    )
    backup_subparsers = backup_parser.add_subparsers(dest="backup_command", required=True)

    # cloop backup create
    backup_create_parser = backup_subparsers.add_parser(
        "create",
        help="Create a new backup",
        description="Create a timestamped backup of all Cloop data",
        epilog="""
Examples:
  # Create backup with default name
  cloop backup create

  # Create named backup
  cloop backup create --name pre-migration

  # Create in specific directory
  cloop backup create --output ~/backups --name weekly
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    backup_create_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output directory for backup (default: data_dir/backups)",
    )
    backup_create_parser.add_argument(
        "--name",
        "-n",
        type=str,
        default="manual",
        help="Backup name for identification (default: manual)",
    )

    # cloop backup restore
    backup_restore_parser = backup_subparsers.add_parser(
        "restore",
        help="Restore from a backup",
        description="Restore databases from a backup archive",
        epilog="""
Examples:
  # Dry run to preview restore
  cloop backup restore backup.cloop.zip --dry-run

  # Force restore with schema mismatch
  cloop backup restore backup.cloop.zip --force

  # Normal restore
  cloop backup restore /path/to/backup.cloop.zip
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    backup_restore_parser.add_argument(
        "backup_path",
        type=Path,
        help="Path to the .cloop.zip backup file",
    )
    backup_restore_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate backup without making changes",
    )
    backup_restore_parser.add_argument(
        "--force",
        action="store_true",
        help="Restore even if schema versions differ",
    )

    # cloop backup list
    backup_list_parser = backup_subparsers.add_parser(
        "list",
        help="List available backups",
        description="List backups in the backup directory",
        epilog="""
Examples:
  # List all backups
  cloop backup list

  # List with custom limit
  cloop backup list --limit 50
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    backup_list_parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=20,
        help="Maximum number of backups to show (default: 20)",
    )

    # cloop backup verify
    backup_verify_parser = backup_subparsers.add_parser(
        "verify",
        help="Verify backup integrity",
        description="Validate backup archive without restoring",
        epilog="""
Examples:
  # Verify a backup file
  cloop backup verify /path/to/backup.cloop.zip
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    backup_verify_parser.add_argument(
        "backup_path",
        type=Path,
        help="Path to the .cloop.zip backup file",
    )

    # cloop backup rotate
    backup_rotate_parser = backup_subparsers.add_parser(
        "rotate",
        help="Rotate old backups",
        description="Delete oldest backups exceeding backup_keep_count",
        epilog="""
Examples:
  # Preview rotation (dry run)
  cloop backup rotate --dry-run

  # Execute rotation
  cloop backup rotate
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    backup_rotate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting",
    )
