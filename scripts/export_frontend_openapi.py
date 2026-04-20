"""Export the FastAPI OpenAPI schema for frontend contract generation.

Purpose:
    Provide the frontend workspace with a deterministic schema file generated
    from the FastAPI application.

Responsibilities:
    - Build the FastAPI app without starting the server.
    - Serialize the OpenAPI document to frontend/openapi.json.
    - Keep frontend contract generation tied to backend Pydantic schemas.

Scope:
    - Schema export only.

Usage:
    - uv run python scripts/export_frontend_openapi.py
    - Root `Makefile` treats this script (plus `frontend/openapi-ts.config.ts`) as inputs to
      `frontend/src/generated/types.gen.ts`; run `make frontend-contracts` to force a refresh
      when backend OpenAPI changes without touching those files.

Invariants/Assumptions:
    - The frontend workspace exists at repo root as frontend/.
    - FastAPI route imports are valid without runtime server startup.
"""

from __future__ import annotations

import json
from pathlib import Path

from cloop.main import create_app


def main() -> None:
    """Export the current FastAPI OpenAPI document for frontend tooling."""
    repo_root = Path(__file__).resolve().parents[1]
    output_path = repo_root / "frontend" / "openapi.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    app = create_app()
    output_path.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
