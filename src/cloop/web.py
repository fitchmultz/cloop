"""Static file serving for Quick Capture UI.

Purpose:
    Serve the single-page HTML UI for loop capture and management.

Responsibilities:
    - Mount static assets directory
    - Serve index.html at root path
    - Serve PWA manifest and service worker with correct headers

Non-scope:
    - API endpoints (see routes/)
    - Template rendering (static files only)

Entrypoint:
    - router: FastAPI APIRouter (mounted at /)
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

_STATIC_DIR = Path(__file__).resolve().parent / "static"

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def serve_index() -> HTMLResponse:
    index_path = _STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    html = index_path.read_text(encoding="utf-8")
    return HTMLResponse(html)


@router.get("/manifest.json")
def serve_manifest() -> FileResponse:
    """Serve the web app manifest with correct content type."""
    manifest_path = _STATIC_DIR / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="manifest.json not found")
    return FileResponse(
        manifest_path,
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/sw.js")
def serve_service_worker() -> FileResponse:
    """Serve service worker with correct headers for SW registration."""
    sw_path = _STATIC_DIR / "sw.js"
    if not sw_path.exists():
        raise HTTPException(status_code=404, detail="sw.js not found")
    return FileResponse(
        sw_path,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache",
            "Service-Worker-Allowed": "/",
        },
    )


router.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
