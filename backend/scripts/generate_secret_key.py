"""Print a new APP_SECRET_KEY (used to encrypt the LLM API keys stored in the database).

    python -m scripts.generate_secret_key

Put the value in .env as APP_SECRET_KEY=... and keep it safe. If it is lost or changed,
the stored API keys can't be read and must be entered again on the admin page.
"""

from cryptography.fernet import Fernet

if __name__ == "__main__":
    print(Fernet.generate_key().decode())
