"""Internal scheduler runtime package.

Purpose:
    Hold focused scheduler implementations behind the public `cloop.scheduler`
    facade.

Responsibilities:
    - Group slot cadence, task execution, side effects, and CLI runtime helpers
    - Keep the public scheduler surface stable while internals stay modular
    - Make scheduler ownership discoverable without one monolithic module

Scope:
    - Internal scheduler runtime modules only

Non-scope:
    - Independent public imports outside `cloop.scheduler`
    - FastAPI app-lifespan background management

Usage:
    - Imported by `cloop.scheduler` and related scheduler internals

Invariants/Assumptions:
    - External callers should continue using `cloop.scheduler`
    - Internal module boundaries may evolve without changing the public facade
"""
