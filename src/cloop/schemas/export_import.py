"""Schemas for export/import operations.

Purpose:
    Define Pydantic models for export/import functionality including filters,
    conflict handling policies, and dry-run preview structures.

Responsibilities:
    - Define schemas for selective export filters (status, project, tag, dates)
    - Define conflict resolution policies (skip, update, fail)
    - Define dry-run preview and import result structures

Non-scope:
    - Database operations (see loops/repo.py)
    - Business logic for import/export (see loops/service.py)
    - CLI argument parsing (see cli_package/parsers/)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ConflictPolicy(str, Enum):
    """How to handle conflicts during import."""

    SKIP = "skip"  # Skip conflicting records, continue with others
    UPDATE = "update"  # Update existing records with imported data
    FAIL = "fail"  # Abort entire import on first conflict


class ExportFilters(BaseModel):
    """Filters for selective loop export."""

    status: list[str] | None = Field(default=None, description="Filter by status values")
    project: str | None = Field(default=None, description="Filter by project name")
    tag: str | None = Field(default=None, description="Filter by tag")
    created_after: datetime | None = Field(
        default=None, description="Only loops created after this UTC datetime"
    )
    created_before: datetime | None = Field(
        default=None, description="Only loops created before this UTC datetime"
    )
    updated_after: datetime | None = Field(
        default=None, description="Only loops updated after this UTC datetime"
    )


class ImportOptions(BaseModel):
    """Options for loop import behavior."""

    dry_run: bool = Field(default=False, description="Preview changes without writing")
    conflict_policy: ConflictPolicy = Field(
        default=ConflictPolicy.FAIL, description="How to handle conflicts"
    )


class ConflictInfo(BaseModel):
    """Information about a detected conflict."""

    imported_loop: dict[str, Any]
    existing_loop_id: int
    match_field: str  # "raw_text" or "title"


class ImportPreview(BaseModel):
    """Preview of import operation (dry-run result)."""

    total_loops: int
    would_create: int
    would_skip: int
    would_update: int
    conflicts: list[ConflictInfo]
    validation_errors: list[dict[str, Any]]


class ImportResult(BaseModel):
    """Result of import operation."""

    imported: int
    skipped: int
    updated: int
    conflicts_detected: int
    dry_run: bool
    preview: ImportPreview | None = None
