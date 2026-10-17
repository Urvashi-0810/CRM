"""DEVELOPMENT ONLY: fill the database with sample demand letters.

Approval arrives in Milestone 4. Until then this script creates approved letters
directly so the demand list, filters, pagination and export can be tried out.

    python -m scripts.seed_demo              # 40 approved + 3 drafts
    python -m scripts.seed_demo --approved 120 --drafts 5

Never run this against the client's real database.
"""

import argparse
import asyncio
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select

from app import models  # noqa: F401
from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker, init_engine
from app.modules.demands.id_allocator import allocate_id_number
from app.modules.demands.models import DemandLetter, DemandTrade
from app.modules.storage import demand_folder
from app.modules.storage.local import LocalStorage
from app.modules.users.models import User

SAMPLES = [
    ("Qatar", "Mosanada Facility Management Services", [
        ("Aspire Zone", "HVAC/Mechanical Engineer", 2), ("Aspire Zone", "Electrical Engineer", 2),
        ("MSY", "Housekeeping Officer", 10), ("Katara Cultural Village", "Electrical Technician", 1)]),
    ("UAE", "Axion Prime Contracting L.L.C", [
        (None, "Civil Engineer", 2), (None, "Infrastructure Foreman", 10),
        (None, "Infrastructure Surveyor", 5), (None, "GRP Pipe Fitter", 50)]),
    ("Qatar", "AQI", [("MASTRO Project", "Senior HVAC Technician", 2)]),
    ("Qatar", "AQI", [
        (None, "HVAC/Chiller Plant Supervisor", 1), (None, "Sr. HVAC Technician", 3),
        (None, "Electrical Technician", 3), (None, "Plumber", 3), (None, "Helper", 2)]),
    ("Qatar", "Telecom O&M Contractor", [
        (None, "Genset Technician", 16), (None, "EM Technician", 18), (None, "Rigger", 19),
        (None, "Helper", 30)]),
    ("Saudi Arabia", "Gulf Construction Co.", [(None, "Mason", 20), (None, "Carpenter", 15)]),
    ("Kuwait", "Al Noor Hospitality", [(None, "Commis Chef", 6), (None, "Waiter", 12)]),
    ("Oman", "Muscat Logistics", [(None, "Heavy Driver", 25)]),
]
TIMELINES = ["30 days", "45 days", "60 days", "Immediate", "By December", None]
ASSIGNEES = ["Anita", "Ravi", "Priya", "Sameer", None]


async def main(approved: int, drafts: int) -> None:
    settings = get_settings()
    init_engine(settings.database_url)
    storage = LocalStorage(settings.storage_root)
    rng = random.Random(42)
    try:
        async with get_sessionmaker()() as db:
            user_id = (
                await db.execute(select(User.id).where(User.is_active).order_by(User.id).limit(1))
            ).scalar_one_or_none()
            if user_id is None:
                raise SystemExit("Create a user first: python -m scripts.bootstrap")

            now = datetime.now(UTC)
            for index in range(approved + drafts):
                is_draft = index >= approved
                country, employer, trades = rng.choice(SAMPLES)
                number = await allocate_id_number(db)
                values = dict(id_number=number, created_by=user_id)
                if not is_draft:
                    when = now - timedelta(days=rng.randint(0, 120), hours=rng.randint(0, 23))
                    values.update(
                        lifecycle="approved", approved_by=user_id, approved_at=when,
                        created_at=when - timedelta(hours=2), country=country, employer=employer,
                        vacancy=sum(t[2] for t in trades),
                        target_timeline=rng.choice(TIMELINES), assign_to=rng.choice(ASSIGNEES),
                    )
                demand_id, code = (
                    await db.execute(
                        insert(DemandLetter).values(**values)
                        .returning(DemandLetter.id, DemandLetter.demand_code)
                    )
                ).one()
                if not is_draft:
                    for pos, (project, trade, qty) in enumerate(trades):
                        db.add(DemandTrade(demand_id=demand_id, project=project, trade=trade,
                                           quantity=qty, sort_order=pos))
                await storage.ensure_folder(demand_folder(code))
                await db.commit()
            print(f"Created {approved} approved and {drafts} draft demo letters.")
    finally:
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--approved", type=int, default=40)
    parser.add_argument("--drafts", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(main(args.approved, args.drafts))
