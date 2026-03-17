"""Internal tool-registry package for Cloop.

Purpose:
    Hold the focused implementations behind the public `cloop.tools` facade.

Responsibilities:
    - Group tool executors by domain
    - Centralize tool-definition and registry helpers
    - Keep the public facade small while preserving stable imports

Scope:
    - Internal tool execution and registration plumbing only

Usage:
    - Imported by `cloop.tools`, not by external callers directly

Invariants/Assumptions:
    - `cloop.tools` remains the canonical public import surface
    - Domain modules expose transport-neutral `ToolDefinition` records
    - Registry assembly preserves stable tool ordering across transports
"""
