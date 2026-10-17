"""Encrypt/decrypt the LLM API keys stored in the database (Fernet, key from APP_SECRET_KEY)."""

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings
from app.errors import ProblemError


def _fernet(settings: Settings) -> Fernet:
    if not settings.app_secret_key:
        raise ProblemError(
            503, "secret-key-missing", "Server encryption key not set",
            "Set APP_SECRET_KEY on the server (python -m scripts.generate_secret_key) and restart.",
        )
    try:
        return Fernet(settings.app_secret_key.encode())
    except ValueError:
        raise ProblemError(
            503, "secret-key-invalid", "Server encryption key is invalid",
            "APP_SECRET_KEY must be a key made by: python -m scripts.generate_secret_key",
        )


def encrypt_api_key(settings: Settings, api_key: str) -> bytes:
    return _fernet(settings).encrypt(api_key.encode())


def decrypt_api_key(settings: Settings, token: bytes) -> str:
    try:
        return _fernet(settings).decrypt(token).decode()
    except InvalidToken:
        raise ProblemError(
            503, "api-key-unreadable", "The stored API key can't be decrypted",
            "APP_SECRET_KEY changed since the key was saved. Enter the API key again on the admin page.",
        )
