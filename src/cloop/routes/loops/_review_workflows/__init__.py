"""Internal review workflow route package.

Purpose:
    Hold feature-owned HTTP review workflow route modules behind the
    canonical `cloop.routes.loops.review_workflows` facade.

Responsibilities:
    - Separate relationship-review and enrichment-review HTTP endpoints by concern
    - Keep the public review workflow router stable while route modules stay focused

Scope:
    - Internal route organization only
    - No new external router surface beyond the facade module

Usage:
    Imported by `cloop.routes.loops.review_workflows`.

Invariants/Assumptions:
    - External callers keep importing the facade router
    - Route paths and response contracts stay unchanged
"""
