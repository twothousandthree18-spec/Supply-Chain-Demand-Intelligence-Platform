"""Phase 6 — Web / Product Presentation Layer: FastAPI app factory.

Serves the static single-page shell (src/web/static) and the /api data-layer
endpoints. Read-only at the data layer: no DDL/DML/ETL is invoked from here.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routers import dashboard, meta
from .settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Supply Chain & Demand Intelligence Platform",
        description="Decision-intelligence web layer over the locked analytical warehouse.",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.include_router(meta.router, prefix="/api")
    app.include_router(dashboard.router, prefix="/api")

    static_dir: Path = settings.static_dir
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    index_file: Path = static_dir / "index.html"

    @app.get("/", include_in_schema=False)
    def shell():
        return FileResponse(index_file)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()