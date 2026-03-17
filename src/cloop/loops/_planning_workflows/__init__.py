"""Internal planning workflow package.

Purpose:
    Hold feature-owned planning workflow modules behind the canonical
    `cloop.loops.planning_workflows` facade.

Responsibilities:
    - Group planning workflow logic by model, generation, snapshot, and execution concerns
    - Keep internal modules importable without exposing a new public namespace

Scope:
    - Internal organization for planning workflow orchestration
    - No independent public API beyond the facade module

Usage:
    Imported by `cloop.loops.planning_workflows` and sibling planning modules.

Invariants/Assumptions:
    - External callers should continue using `cloop.loops.planning_workflows`
    - Internal modules may evolve as long as the facade contract stays stable
"""
