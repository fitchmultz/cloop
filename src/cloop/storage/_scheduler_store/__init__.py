"""Internal scheduler storage modules.

Purpose:
    Group focused scheduler persistence helpers behind the canonical
    `cloop.storage.scheduler_store` facade.

Responsibilities:
    - Organize scheduler task-run, schedule, and push-dedupe persistence code
    - Provide narrow internal import targets for scheduler runtime modules
    - Keep scheduler storage ownership discoverable without one large module

Scope:
    - Internal scheduler storage implementation modules only

Usage:
    - Imported by `cloop.storage.scheduler_store` and scheduler runtime internals

Invariants/Assumptions:
    - External callers should keep importing `cloop.storage.scheduler_store` or
      `cloop.storage`
    - Internal module boundaries may evolve without changing the public facade

Non-scope:
    - Public storage re-export surfaces outside `cloop.storage.scheduler_store`
    - Scheduler cadence calculations, task orchestration, or CLI behavior
"""
