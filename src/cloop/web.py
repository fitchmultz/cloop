from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

_STATIC_DIR = Path(__file__).resolve().parent / "static"

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def serve_index() -> HTMLResponse:
    html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


router.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
