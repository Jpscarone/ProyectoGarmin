from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.models.user import User
from app.db.session import SessionLocal
from app.services.security import hash_password
from app.services.user_permission_service import ROLE_ADMIN


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the first admin user for training_app.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--password", default=None)
    args = parser.parse_args()

    password = args.password or getpass.getpass("Password: ")
    if not password.strip():
        raise SystemExit("Password cannot be empty.")

    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.email == args.email.strip().lower()))
        if existing is not None:
            raise SystemExit(f"User with email {args.email} already exists.")

        user = User(
            email=args.email.strip().lower(),
            name=args.name.strip(),
            password_hash=hash_password(password),
            role=ROLE_ADMIN,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Admin user created: id={user.id} email={user.email}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
