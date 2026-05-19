from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.models.athlete import Athlete
from app.db.session import SessionLocal
from app.services.athlete_access_code_service import create_athlete_access_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an athlete access code for ProyectoGarmin MCP experimental access.")
    parser.add_argument("--athlete-id", type=int, required=True)
    parser.add_argument("--label", default=None)
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--code", default=None)
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        athlete = db.get(Athlete, int(args.athlete_id))
        if athlete is None:
            raise SystemExit(f"Athlete with id={args.athlete_id} does not exist.")
        access_code = create_athlete_access_code(
            db,
            athlete=athlete,
            label=args.label,
            code=args.code,
            prefix=args.prefix,
            notes=args.notes,
        )
        print(
            "Athlete access code created:",
            f"id={access_code.id}",
            f"athlete_id={athlete.id}",
            f"athlete_name={athlete.name}",
            f"access_code={access_code.access_code}",
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
