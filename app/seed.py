from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User

# Seeded demo accounts. Auth is mocked: the browser picks one of these users.
SEED_USERS = [
    ("Alice Kim", "alice@ajaia.test"),
    ("Bob Lee", "bob@ajaia.test"),
    ("Carol Diaz", "carol@ajaia.test"),
]


def seed_users(db: Session) -> None:
    existing = set(db.scalars(select(User.email)))
    for name, email in SEED_USERS:
        if email not in existing:
            db.add(User(name=name, email=email))
    db.commit()
