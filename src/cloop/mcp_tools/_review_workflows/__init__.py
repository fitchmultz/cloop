"""Internal MCP review workflow tool package.

Purpose:
    Hold feature-owned MCP review workflow tool modules behind the
    canonical `cloop.mcp_tools.review_workflows` facade.

Responsibilities:
    - Separate relationship-review and enrichment-review MCP tools by concern
    - Keep the public review workflow registration surface stable

Scope:
    - Internal MCP tool organization only
    - No new public namespace beyond the facade module

Usage:
    Imported by `cloop.mcp_tools.review_workflows`.

Invariants/Assumptions:
    - External callers keep using the facade registration function
    - Tool names and docstrings stay aligned with existing operator docs
"""
