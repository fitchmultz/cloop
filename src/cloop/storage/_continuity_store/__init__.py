"""Internal continuity storage modules.

Purpose:
    Group focused continuity persistence helpers behind the canonical
    `cloop.storage.continuity_store` facade.

Responsibilities:
    - Organize outcomes, markers, workflow summaries, notifications, snapshot
      assembly, and delivery inspection persistence code
    - Provide narrow internal import targets for continuity storage evolution
    - Keep continuity storage ownership discoverable without one large module

Scope:
    - Internal continuity storage implementation modules only

Usage:
    - Imported by `cloop.storage.continuity_store` and related storage tests

Invariants/Assumptions:
    - External callers should keep importing `cloop.storage.continuity_store` or
      `cloop.storage`
    - Internal module boundaries may evolve without changing the public facade

Non-scope:
    - Public storage re-export surfaces outside `cloop.storage.continuity_store`
    - HTTP, CLI, MCP transport contracts
"""
