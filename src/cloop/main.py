"""Cloop FastAPI application entry point.

Purpose:
    Create and configure the FastAPI application with all routers.

Responsibilities:
    - FastAPI app creation and lifespan management
    - Router mounting for modular endpoints
    - Static file serving for web UI

Non-scope:
    - Business logic (see loops/service.py)
    - Database schema (see db.py)
- Exception handler registration
- Health endpoint (kept here for simplicity)

All request/response models are in schemas/
All route handlers are in routes/
All exception handlers are in handlers.py
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Dict

from fastapi import Depends, FastAPI

from . import db, web
from .handlers import register_exception_handlers
from .rag import _SQL_PY_METRIC, _VECLIKE_METRIC, _select_retrieval_order
from .routes import chat_router, loops_router, rag_router
from .schemas.health import DependencyStatus, HealthResponse
from .settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db.init_databases(get_settings())
    yield


app = FastAPI(title="Cloop LLM Service", version="0.1.0", lifespan=lifespan)
app.include_router(web.router)
app.include_router(chat_router)
app.include_router(loops_router)
app.include_router(rag_router)
register_exception_handlers(app)


def get_app_settings() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


@app.get("/health", response_model=HealthResponse)
def health_endpoint(settings: SettingsDep) -> HealthResponse:
    # Run dependency checks
    db_checks = db.check_database_connectivity(settings)

    # Build check status objects
    checks: Dict[str, DependencyStatus] = {}
    all_ok = True

    for name, result in db_checks.items():
        checks[name] = DependencyStatus(
            ok=result["ok"],
            latency_ms=result["latency_ms"],
            error=result.get("error"),
        )
        if not result["ok"]:
            all_ok = False

    # Get existing configuration info
    backend = db.get_vector_backend()
    vector_available = db.vector_extension_available()
    vector_load_error = db.get_vector_load_error()
    order = [
        path.value
        for path in _select_retrieval_order(backend=backend, scope=None, settings=settings)
    ]
    metric = (
        _VECLIKE_METRIC
        if backend in {db.VectorBackend.VEC, db.VectorBackend.VSS}
        else _SQL_PY_METRIC
    )

    return HealthResponse(
        ok=all_ok,  # Now based on actual dependency health
        model=settings.llm_model,
        vector_mode=settings.vector_search_mode.value,
        vector_backend=backend.value,
        vector_available=vector_available,
        vector_load_error=vector_load_error,
        core_db=settings.core_db_path.name,
        rag_db=settings.rag_db_path.name,
        schema_version=db.SCHEMA_VERSION,
        embed_storage=settings.embed_storage_mode.value,
        tool_mode_default=settings.tool_mode_default.value,
        retrieval_order=order,
        retrieval_metric=metric,
        checks=checks,
    )
