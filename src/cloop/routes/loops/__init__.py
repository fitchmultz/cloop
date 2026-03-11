"""Loop routes package - combines all loop sub-routers.

Purpose:
    Exports a unified APIRouter that includes all loop-related endpoints
    organized by domain across multiple focused modules.

Modules:
- lifecycle: Loop capture and mutation endpoints
- query: Loop listing, search, next, review, and tags
- import_export: Loop import/export endpoints
- metrics: Workflow metrics endpoints
- suggestions_clarifications: Suggestion and clarification endpoints
- dependencies: Loop dependency management (blockers, dependents)
- views: Saved views for filtered queries
- templates: Loop templates for pre-filled capture
- claims: Loop claim management (exclusive access leases)
- events: Event history and undo operations
- webhooks: Webhook subscription management
- bulk: Bulk operations (update, close, snooze)
- timers: Time tracking sessions
- comments: Threaded comments on loops
- duplicates: Duplicate detection and merge operations

Route Ordering:
    Routers are included from most specific (static paths) to least specific
    (dynamic paths like /{loop_id}) to ensure proper route matching.
"""

from fastapi import APIRouter

# Export shared utilities
from ._common import IdempotencyKeyHeader, SettingsDep
from .bulk import router as bulk_router
from .claims import router as claims_router
from .comments import router as comments_router
from .dependencies import router as dependencies_router
from .duplicates import router as duplicates_router
from .events import router as events_router
from .import_export import router as import_export_router
from .lifecycle import router as lifecycle_router
from .metrics import router as metrics_router
from .push import router as push_router
from .query import router as query_router
from .suggestions_clarifications import router as suggestions_clarifications_router
from .templates import router as templates_router
from .timers import router as timers_router
from .views import router as views_router
from .webhooks import router as webhooks_router

# Create main router with prefix
router = APIRouter(prefix="/loops", tags=["loops"])

# Include routers in order from MOST SPECIFIC to LEAST SPECIFIC
# Static paths must be registered BEFORE dynamic /{loop_id} routes
# to prevent /{loop_id} from matching static names like "templates", "views", etc.

# 1. Bulk operations - static paths: /bulk/*
router.include_router(bulk_router)

# 2. Webhooks - static paths: /webhooks/*
router.include_router(webhooks_router)

# 3. Views - static paths: /views/*
router.include_router(views_router)

# 4. Templates - static paths: /templates/*
router.include_router(templates_router)

# 5. Query / export / metrics / suggestion endpoints - static paths first
router.include_router(query_router)
router.include_router(import_export_router)
router.include_router(metrics_router)
router.include_router(suggestions_clarifications_router)
router.include_router(claims_router)

# 6. Lifecycle router - includes dynamic /{loop_id} routes
router.include_router(lifecycle_router)

# 7. Push subscriptions - static paths: /push/*
router.include_router(push_router)

# 8. Loop-specific nested routes - all start with /{loop_id}/...
# These are least specific and should be registered last
router.include_router(dependencies_router)
router.include_router(events_router)
router.include_router(timers_router)
router.include_router(comments_router)
router.include_router(duplicates_router)

__all__ = [
    "router",
    "SettingsDep",
    "IdempotencyKeyHeader",
]
