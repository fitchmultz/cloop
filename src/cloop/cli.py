"""CLI entry point for Cloop.

Purpose:
    Re-export CLI components from the cli package for backwards compatibility.

Responsibilities:
    - Expose main CLI entry point and parser builder
    - Maintain backwards compatibility for existing imports

Non-scope:
    - CLI implementation details (see cli/ package)
"""

from __future__ import annotations

from argparse import Namespace
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from cloop.settings import Settings

    CommandFunc = Callable[[Namespace, "Settings"], int]

# Re-export command handlers for backwards compatibility (tests access these)
from cloop.cli_package.backup_commands import (
    backup_create_command,  # noqa: F401
    backup_list_command,  # noqa: F401
    backup_restore_command,  # noqa: F401
    backup_rotate_command,  # noqa: F401
    backup_verify_command,  # noqa: F401
)
from cloop.cli_package.loop_claim_commands import (  # noqa: F401
    loop_claim_command,  # noqa: F401
    loop_force_release_claim_command,
    loop_get_claim_command,  # noqa: F401
    loop_list_claims_command,  # noqa: F401
    loop_release_claim_command,  # noqa: F401
    loop_renew_claim_command,  # noqa: F401
)
from cloop.cli_package.loop_core_commands import (
    capture_command,  # noqa: F401
    inbox_command,  # noqa: F401
    loop_close_command,  # noqa: F401
    loop_enrich_command,  # noqa: F401
    loop_get_command,  # noqa: F401
    loop_list_command,  # noqa: F401
    loop_search_command,  # noqa: F401
    loop_snooze_command,  # noqa: F401
    loop_status_command,  # noqa: F401
    loop_update_command,  # noqa: F401
    next_command,  # noqa: F401
)
from cloop.cli_package.loop_dep_commands import loop_dep_command  # noqa: F401
from cloop.cli_package.loop_misc_commands import (
    export_command,  # noqa: F401
    import_command,  # noqa: F401
    loop_events_command,  # noqa: F401
    loop_metrics_command,  # noqa: F401
    loop_review_command,  # noqa: F401
    loop_undo_command,  # noqa: F401
    projects_command,  # noqa: F401
    suggestion_apply_command,  # noqa: F401
    suggestion_list_command,  # noqa: F401
    suggestion_reject_command,  # noqa: F401
    suggestion_show_command,  # noqa: F401
    tags_command,  # noqa: F401
)
from cloop.cli_package.loop_timer_commands import (
    sessions_command,  # noqa: F401
    timer_command,  # noqa: F401
)
from cloop.cli_package.loop_view_commands import (
    loop_view_apply_command,  # noqa: F401
    loop_view_create_command,  # noqa: F401
    loop_view_delete_command,  # noqa: F401
    loop_view_get_command,  # noqa: F401
    loop_view_list_command,  # noqa: F401
    loop_view_update_command,  # noqa: F401
)
from cloop.cli_package.main import build_parser, main
from cloop.cli_package.rag_commands import (
    ask_command,  # noqa: F401
    ingest_command,  # noqa: F401
)
from cloop.cli_package.template_commands import (
    template_create_command,  # noqa: F401
    template_delete_command,  # noqa: F401
    template_from_loop_command,  # noqa: F401
    template_list_command,  # noqa: F401
    template_show_command,  # noqa: F401
)

# Re-export functions that tests monkeypatch
from cloop.loops.service import request_enrichment  # noqa: F401

# Provide underscore-prefixed aliases for test compatibility
_ingest_command: "CommandFunc" = ingest_command
_ask_command: "CommandFunc" = ask_command
_capture_command: "CommandFunc" = capture_command
_inbox_command: "CommandFunc" = inbox_command
_next_command: "CommandFunc" = next_command
_loop_get_command: "CommandFunc" = loop_get_command
_loop_list_command: "CommandFunc" = loop_list_command
_loop_search_command: "CommandFunc" = loop_search_command
_loop_update_command: "CommandFunc" = loop_update_command
_loop_status_command: "CommandFunc" = loop_status_command
_loop_close_command: "CommandFunc" = loop_close_command
_loop_enrich_command: "CommandFunc" = loop_enrich_command
_loop_snooze_command: "CommandFunc" = loop_snooze_command
_loop_view_create_command: "CommandFunc" = loop_view_create_command
_loop_view_list_command: "CommandFunc" = loop_view_list_command
_loop_view_get_command: "CommandFunc" = loop_view_get_command
_loop_view_update_command: "CommandFunc" = loop_view_update_command
_loop_view_delete_command: "CommandFunc" = loop_view_delete_command
_loop_view_apply_command: "CommandFunc" = loop_view_apply_command
_loop_claim_command: "CommandFunc" = loop_claim_command
_loop_renew_claim_command: "CommandFunc" = loop_renew_claim_command
_loop_release_claim_command: "CommandFunc" = loop_release_claim_command
_loop_get_claim_command: "CommandFunc" = loop_get_claim_command
_loop_list_claims_command: "CommandFunc" = loop_list_claims_command
_loop_force_release_claim_command: "CommandFunc" = loop_force_release_claim_command
_loop_dep_command: "CommandFunc" = loop_dep_command
_timer_command: "CommandFunc" = timer_command
_sessions_command: "CommandFunc" = sessions_command
_loop_review_command: "CommandFunc" = loop_review_command
_loop_events_command: "CommandFunc" = loop_events_command
_loop_undo_command: "CommandFunc" = loop_undo_command
_loop_metrics_command: "CommandFunc" = loop_metrics_command
_tags_command: "CommandFunc" = tags_command
_projects_command: "CommandFunc" = projects_command
_export_command: "CommandFunc" = export_command
_import_command: "CommandFunc" = import_command
_backup_create_command: "CommandFunc" = backup_create_command
_backup_restore_command: "CommandFunc" = backup_restore_command
_backup_list_command: "CommandFunc" = backup_list_command
_backup_verify_command: "CommandFunc" = backup_verify_command
_backup_rotate_command: "CommandFunc" = backup_rotate_command
_suggestion_list_command: "CommandFunc" = suggestion_list_command
_suggestion_show_command: "CommandFunc" = suggestion_show_command
_suggestion_apply_command: "CommandFunc" = suggestion_apply_command
_suggestion_reject_command: "CommandFunc" = suggestion_reject_command
_template_list_command: "CommandFunc" = template_list_command
_template_show_command: "CommandFunc" = template_show_command
_template_create_command: "CommandFunc" = template_create_command
_template_delete_command: "CommandFunc" = template_delete_command
_template_from_loop_command: "CommandFunc" = template_from_loop_command

__all__ = ["build_parser", "main"]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
