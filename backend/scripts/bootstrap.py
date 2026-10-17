"""One-time setup: create the first user and set the admin password.

Usage (from the backend folder, with DATABASE_URL set):

    python -m scripts.bootstrap

You are asked for each value interactively. For automation, values can also be
passed as environment variables:
    BOOTSTRAP_USERNAME, BOOTSTRAP_DISPLAY_NAME, BOOTSTRAP_ROLE,
    BOOTSTRAP_PASSWORD, BOOTSTRAP_ADMIN_PASSWORD

Run it again with --reset-admin-password to replace a forgotten admin password.
"""

import argparse
import asyncio
import getpass
import os
import re
import sys

from sqlalchemy import func, select

from app import models  # noqa: F401
from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker, init_engine
from app.modules.admin import service as admin_service
from app.modules.users.models import User
from app.security import hash_password


def _ask(env: str, prompt: str, *, secret: bool = False, default: str | None = None) -> str:
    value = os.environ.get(env)
    if value:
        return value
    while True:
        if secret:
            first = getpass.getpass(f"{prompt}: ")
            second = getpass.getpass(f"{prompt} (again): ")
            if first != second:
                print("  Values did not match, try again.")
                continue
            value = first
        else:
            suffix = f" [{default}]" if default else ""
            value = input(f"{prompt}{suffix}: ").strip() or (default or "")
        if value:
            return value


def _check_password(value: str, label: str) -> None:
    minimum = get_settings().password_min_length
    if len(value) < minimum:
        sys.exit(f"{label} must be at least {minimum} characters.")


async def main(reset_admin_password: bool) -> None:
    settings = get_settings()
    init_engine(settings.database_url)
    try:
        async with get_sessionmaker()() as db:
            user_count = (await db.execute(select(func.count(User.id)))).scalar_one()
            admin_set = await admin_service.admin_password_configured(db)

            if user_count == 0:
                print("Creating the first user account.")
                username = _ask("BOOTSTRAP_USERNAME", "Username (3-50 letters, digits, . _ -)")
                if not re.fullmatch(r"[A-Za-z0-9._-]{3,50}", username):
                    sys.exit("Username must be 3-50 characters: letters, digits, dot, underscore, hyphen.")
                display_name = _ask("BOOTSTRAP_DISPLAY_NAME", "Display name")
                role = os.environ.get("BOOTSTRAP_ROLE") or input("Role / job title (optional): ").strip()
                password = _ask("BOOTSTRAP_PASSWORD", "Password", secret=True)
                _check_password(password, "Password")
                db.add(
                    User(
                        username=username,
                        display_name=display_name,
                        role=role,
                        password_hash=hash_password(password),
                    )
                )
                await db.commit()
                print(f'  User "{username}" created.')
            else:
                print(f"{user_count} user(s) already exist; skipping user creation.")

            if not admin_set or reset_admin_password:
                print("Setting the admin password (needed to open the admin page).")
                admin_password = _ask("BOOTSTRAP_ADMIN_PASSWORD", "Admin password", secret=True)
                _check_password(admin_password, "Admin password")
                await admin_service.set_admin_password(db, admin_password)
                print("  Admin password saved.")
            else:
                print("Admin password already set; use --reset-admin-password to replace it.")
    finally:
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--reset-admin-password", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.reset_admin_password))
