"""Test setup: a real PostgreSQL database, migrated with Alembic, emptied between tests.

Set TEST_DATABASE_URL to point at an empty database you don't mind being wiped, e.g.
    postgresql+asyncpg://crm:crm@localhost:5432/crm_test
"""

import asyncio
import os
import shutil
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.config import Settings
from app.db import dispose_engine, get_sessionmaker, init_engine
from app.main import create_app
from app.modules.admin import service as admin_service
from app.modules.llm.prompts import DEFAULT_BASE_PROMPT
from app.modules.storage import get_storage
from app.modules.users.models import User
from app.security import hash_password

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://crm:crm@localhost:5432/crm_test"
)
BACKEND_DIR = Path(__file__).resolve().parents[1]

USER_PASSWORD = "user-password-1"
TEST_SECRET_KEY = "Qm9ndXMta2V5LWZvci10ZXN0cy1vbmx5LTEyMzQ1Njc="  # valid Fernet key (32 bytes)
ADMIN_PASSWORD = "admin-password-1"


@pytest.fixture(scope="session")
def migrated_database():
    """Rebuild the schema from scratch with the real migrations (tests them too)."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL

    async def reset():
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(TEST_DATABASE_URL)
        async with engine.begin() as conn:
            await conn.execute(text("drop schema public cascade"))
            await conn.execute(text("create schema public"))
        await engine.dispose()

    asyncio.run(reset())
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(scope="session")
def storage_root(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("storage")


@pytest.fixture(scope="session")
def settings(storage_root) -> Settings:
    return Settings(
        database_url=TEST_DATABASE_URL,
        cookie_secure=False,
        admin_max_failed_attempts=3,
        admin_lockout_minutes=15,
        password_min_length=6,
        storage_root=str(storage_root),
        app_secret_key=TEST_SECRET_KEY,
        max_file_mb=10,
        max_letter_inputs_mb=20,
        max_images_per_letter=20,
    )


@pytest.fixture(scope="session")
async def app(migrated_database, settings):
    init_engine(settings.database_url)
    yield create_app(settings)
    await dispose_engine()


@pytest.fixture(autouse=True)
async def clean_tables(app, storage_root):
    async with get_sessionmaker()() as db:
        await db.execute(
            text(
                "truncate reference_letters, llm_calls, letter_versions, letterheads, llm_provider_configs, "
                "generation_jobs, chat_messages, idempotency_keys, files, demand_trades, "
                "demand_letters, sessions, name_change_requests, app_settings, users "
                "restart identity cascade"
            )
        )
        # The truncate cascades to prompt_versions (FK to users); restore the default prompt.
        await db.execute(
            text("insert into prompt_versions (body, is_active) values (:b, true)"),
            {"b": DEFAULT_BASE_PROMPT},
        )
        await db.commit()
    shutil.rmtree(storage_root / "demands", ignore_errors=True)
    app.dependency_overrides.pop(get_storage, None)
    yield


@pytest.fixture
async def make_user():
    async def _make(username: str, display_name: str | None = None, role: str = "", active=True):
        async with get_sessionmaker()() as db:
            user = User(
                username=username,
                display_name=display_name or username.title(),
                role=role,
                password_hash=hash_password(USER_PASSWORD),
                is_active=active,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user

    return _make


@pytest.fixture
async def admin_password_set():
    async with get_sessionmaker()() as db:
        await admin_service.set_admin_password(db, ADMIN_PASSWORD)


class ApiClient(httpx.AsyncClient):
    """httpx client that remembers the CSRF token and sends it on writes."""

    csrf: str | None = None

    async def request(self, method, url, **kwargs):
        if method.upper() not in {"GET", "HEAD", "OPTIONS"} and self.csrf:
            headers = dict(kwargs.pop("headers", None) or {})
            headers.setdefault("X-CSRF-Token", self.csrf)
            kwargs["headers"] = headers
        return await super().request(method, url, **kwargs)


@pytest.fixture
async def client(app):
    async with ApiClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def new_client(app):
    """Factory for extra independent browsers (separate cookie jars)."""
    clients = []

    async def _new():
        c = ApiClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        clients.append(c)
        return c

    yield _new
    for c in clients:
        await c.aclose()


async def login(client: ApiClient, username: str, password: str = USER_PASSWORD) -> httpx.Response:
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    if response.status_code == 200:
        client.csrf = response.json()["csrf_token"]
    return response


async def unlock_admin(client: ApiClient, password: str = ADMIN_PASSWORD) -> httpx.Response:
    return await client.post("/api/v1/admin/session", json={"admin_password": password})
