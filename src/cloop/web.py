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
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from ._version import __version__

_STATIC_DIR = Path(__file__).resolve().parent / "static"

router = APIRouter()


def _static_file_response(
    filename: str,
    *,
    media_type: str,
    cache_control: str,
    extra_headers: dict[str, str] | None = None,
) -> FileResponse:
    """Serve a root-level static asset with explicit headers."""
    file_path = _STATIC_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found")
    headers = {"Cache-Control": cache_control}
    if extra_headers:
        headers.update(extra_headers)
    return FileResponse(file_path, media_type=media_type, headers=headers)


class CloopStaticFiles(StaticFiles):
    """Static file server with safer cache headers for mutable frontend assets."""

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        media_type = response.media_type or ""
        if media_type.startswith(("text/css", "application/javascript", "text/javascript")):
            response.headers["Cache-Control"] = "no-cache"
        return response


@router.get("/", response_class=HTMLResponse)
def serve_index() -> HTMLResponse:
    index_path = _STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    html = index_path.read_text(encoding="utf-8")
    asset_version = __version__
    for asset_path in (
        "/static/css/tokens.css",
        "/static/css/base.css",
        "/static/css/components.css",
        "/static/css/loop.css",
        "/static/css/review.css",
        "/static/css/chat-rag.css",
        "/static/css/comments.css",
        "/static/css/layout.css",
        "/static/css/modals.css",
        "/static/js/init.js",
    ):
        html = html.replace(asset_path, f"{asset_path}?v={asset_version}")
    return HTMLResponse(html)


@router.get("/manifest.json")
def serve_manifest() -> FileResponse:
    """Serve the web app manifest with correct content type."""
    return _static_file_response(
        "manifest.json",
        media_type="application/manifest+json",
        cache_control="public, max-age=86400",
    )


@router.api_route("/favicon.ico", methods=["GET", "HEAD"])
def serve_favicon() -> FileResponse:
    """Serve the browser favicon from the canonical root path."""
    return _static_file_response(
        "favicon.ico",
        media_type="image/x-icon",
        cache_control="public, max-age=86400",
    )


@router.get("/sw.js")
def serve_service_worker() -> FileResponse:
    """Serve service worker with correct headers for SW registration."""
    return _static_file_response(
        "sw.js",
        media_type="application/javascript",
        cache_control="no-cache",
        extra_headers={"Service-Worker-Allowed": "/"},
    )


# Note: Static files are mounted directly on the app in main.py
# APIRouter.mount() doesn't propagate when included via include_router()
