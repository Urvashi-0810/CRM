"""FastAPI application entry point.

Run locally:  uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from app import models  # noqa: F401  (registers all tables)
from app.config import Settings, get_settings
from app.db import dispose_engine, get_sessionmaker, init_engine
from app.errors import ProblemError, register_error_handlers
from app.modules.admin.router import router as admin_router
from app.modules.auth.router import router as auth_router
from app.modules.ai_admin.router import router as ai_router
from app.modules.chat.router import router as chat_router
from app.modules.ads.router import router as ads_router
from app.modules.demands.router import router as demands_router
from app.modules.letters.router import router as letters_router
from app.modules.users.router import router as me_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_engine(settings.database_url)
        yield
        await dispose_engine()

    app = FastAPI(
        title="Demand Letter CRM API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    register_error_handlers(app)

    api = APIRouter(prefix="/api/v1")
    api.include_router(auth_router)
    api.include_router(me_router)
    api.include_router(admin_router)
    api.include_router(demands_router)
    api.include_router(chat_router)
    api.include_router(letters_router)
    api.include_router(ai_router)
    api.include_router(ads_router)
    app.include_router(api)

    @app.get("/healthz", tags=["operations"])
    async def healthz():
        try:
            async with get_sessionmaker()() as session:
                await session.execute(text("select 1"))
        except Exception:
            raise ProblemError(503, "database-unavailable", "Database unavailable")
        return {"status": "ok"}

    return app


app = create_app()
