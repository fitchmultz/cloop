"""Internal review workflow package.

Purpose:
    Hold feature-owned review workflow modules behind the canonical
    `cloop.loops.review_workflows` facade.

Responsibilities:
    - Group review workflow logic by shared helpers, snapshots, actions, sessions, and execution
    - Keep durable review workflows organized without changing the public import path

Scope:
    - Internal organization only
    - No independent public API beyond the facade module

Usage:
    Imported by `cloop.loops.review_workflows` and sibling workflow modules.

Invariants/Assumptions:
    - External callers keep using `cloop.loops.review_workflows`
    - Internal structure may evolve while the facade contract stays stable
"""
