"""Purpose: Lock in the lightweight package boundary for Cloop imports.

Responsibilities:
    - Verify `import cloop` does not boot the FastAPI app or heavy runtime modules.
    - Verify common package-submodule imports stay lightweight.
    - Verify the package root no longer re-exports the FastAPI app.
    - Verify explicit `cloop.main` app entrypoints still work.

Scope:
    - Import-boundary regression coverage for package and app entrypoints.
    - Subprocess-based checks that avoid cross-test `sys.modules` contamination.

Usage:
    - Run `uv run pytest tests/test_package_boundary.py -q`.
    - The default `make ci` path also covers these checks.

Invariants/Assumptions:
    - `import cloop` must remain lightweight.
    - FastAPI access lives under `cloop.main`, not the package root.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HEAVY_MODULES = ("cloop.main", "cloop.ai_bridge", "cloop.rag", "fastapi")


def _run_python(code: str) -> subprocess.CompletedProcess[str]:
    """Run a short Python snippet inside the repo's active environment."""
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_package_root_import_stays_lightweight() -> None:
    """`import cloop` should not load app/runtime modules as a side effect."""
    completed = _run_python(
        "import json, sys; import cloop; "
        "heavy = sorted(name for name in "
        f"{HEAVY_MODULES!r} if name in sys.modules); "
        "print(json.dumps({'heavy': heavy, 'version': cloop.__version__})); "
        "raise SystemExit(0 if not heavy else 1)"
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["heavy"] == []
    assert payload["version"]


def test_package_submodule_import_stays_lightweight() -> None:
    """`from cloop import db` should not boot the app/runtime graph."""
    completed = _run_python(
        "import json, sys; from cloop import db; "
        "heavy = sorted(name for name in "
        f"{HEAVY_MODULES!r} if name in sys.modules); "
        "print(json.dumps({'db_module': db.__name__, 'heavy': heavy})); "
        "raise SystemExit(0 if not heavy else 1)"
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["db_module"] == "cloop.db"
    assert payload["heavy"] == []


def test_package_root_no_longer_exports_app() -> None:
    """`from cloop import app` should fail after the package-boundary cutover."""
    completed = _run_python(
        "try:\n"
        "    from cloop import app\n"
        "except ImportError:\n"
        "    print('removed')\n"
        "    raise SystemExit(0)\n"
        "else:\n"
        "    raise SystemExit(1)\n"
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert completed.stdout.strip() == "removed"


def test_explicit_main_entrypoint_exports_app_factory() -> None:
    """`cloop.main` should remain the explicit app bootstrap surface."""
    completed = _run_python(
        "from cloop.main import app, create_app; "
        "fresh_app = create_app(); "
        "same_version = app.version == fresh_app.version; "
        "print(app.__class__.__name__, fresh_app.__class__.__name__, same_version)"
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert completed.stdout.strip() == "FastAPI FastAPI True"
