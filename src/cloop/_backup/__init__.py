"""Internal backup package for Cloop.

Purpose:
    Hold focused backup and restore implementations behind the public
    `cloop.backup` facade.

Responsibilities:
    - Group backup metadata, archive IO, restore, verification, and inventory helpers
    - Keep the public backup surface stable while runtime internals stay modular
    - Make backup ownership discoverable without a monolithic module

Scope:
    - Internal backup/restore implementation modules only

Non-scope:
    - Independent public imports outside `cloop.backup`
    - Scheduler-triggered automation behavior

Usage:
    - Imported by `cloop.backup` and related internal modules

Invariants/Assumptions:
    - External callers should continue using `cloop.backup`
    - Internal module boundaries may evolve without changing the public facade
"""
