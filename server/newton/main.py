"""Compose local services, authenticated APIs and the compiled Newton interface."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from newton import (
    auth,
    budget,
    companies,
    investigation_run,
    investigations,
    onboarding,
    onboarding_worker,
    providers,
    retrieval,
    sources,
    visual_retrieval,
)
from newton.db import SessionLocal, engine, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize storage before serving and release pooled connections on shutdown."""
    try:
        init_db()
        with SessionLocal() as db:
            onboarding_worker.recover(db)
        retrieval.initialize()
        visual_retrieval.initialize()
        yield
    finally:
        engine.dispose()


app = FastAPI(
    title="Newton investigation API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
# Bound parsing itself; the separate 64 MiB original limit excludes multipart overhead.
app.add_middleware(RequestBodyLimitMiddleware, max_body_size=65 * 1024 * 1024)


@app.middleware("http")
async def protect_local_boundary(request: Request, call_next):
    """Reject cross-origin writes and prevent caching private API responses."""
    origin = request.headers.get("origin")
    expected = str(request.base_url).rstrip("/")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin != expected:
        return JSONResponse({"detail": "Cross-origin writes are not allowed."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health() -> dict:
    """Expose actual dependency status and credential availability without secrets."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    with retrieval.connection() as client:
        ready = client.is_ready()
    try:
        totals = budget.summary()
    except budget.BudgetExceeded:
        totals = {"ceiling_eur": 0, "spent_eur": 0, "reserved_eur": 0}
    return {
        "status": "ok" if ready else "degraded",
        "database": "ready",
        "retrieval": "ready" if ready else "unavailable",
        "providers": providers.available_models(),
        "budget": totals,
    }


for router in [
    auth.router,
    companies.router,
    investigations.router,
    investigation_run.router,
    sources.router,
    onboarding.router,
]:
    app.include_router(router, prefix="/api")

frontend = Path(__file__).resolve().parents[2] / "web" / "dist"
if frontend.exists():
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
