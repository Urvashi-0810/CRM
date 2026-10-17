"""Application settings, read from environment variables (or a .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # PostgreSQL connection, async driver. Example:
    # postgresql+asyncpg://crm:crm@localhost:5432/crm
    database_url: str = "postgresql+asyncpg://crm:Nishi1509@localhost:5432/crm"

    # Login session lifetime (absolute, from login).
    session_ttl_hours: int = 12
    # How long the admin page stays unlocked after entering the admin password.
    admin_session_minutes: int = 30
    # Wrong admin-password attempts allowed before a temporary lock.
    admin_max_failed_attempts: int = 5
    admin_lockout_minutes: int = 15

    # Minimum length for user and admin passwords.
    password_min_length: int = 6

    # Root folder for stored files (inquiries, JDs, generated letters).
    # One sub-folder per demand: <storage_root>/demands/<demand code>/
    storage_root: str = "./storage"

    # Key used to encrypt the LLM API keys stored in the database (Fernet key).
    # Generate one with:  python -m scripts.generate_secret_key
    # Keep it outside the database; losing it means re-entering the API keys.
    app_secret_key: str | None = None

    # Upload limits ("file too large" above these).
    max_file_mb: int = 10           # per file
    max_letter_inputs_mb: int = 20  # all files attached to one letter, together
    max_images_per_letter: int = 20

    # Background worker.
    worker_concurrency: int = 10
    job_lease_seconds: int = 300

    # Development only: enables a "Test (no AI)" provider that returns canned letters,
    # so the flow can be tried without an API key. Never enable in production.
    llm_allow_test_provider: bool = False

    # Must be true whenever the app is served over HTTPS (always in production).
    # Set to false only for local development over plain http://localhost.
    cookie_secure: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
