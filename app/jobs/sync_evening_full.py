from __future__ import annotations

import argparse
from datetime import date
import json
import logging
import sys

from app.db.session import SessionLocal
from app.services.scheduled_sync_service import run_evening_full_job


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scheduled Garmin evening full sync.")
    parser.add_argument("--athlete-id", type=int, default=None, help="Procesa solo un atleta.")
    parser.add_argument("--date", type=str, default=None, help="Fecha de referencia YYYY-MM-DD.")
    parser.add_argument("--force", action="store_true", help="Amplia la ventana y rehace analisis necesarios.")
    parser.add_argument("--dry-run", action="store_true", help="No modifica datos, solo informa los parametros recibidos.")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = _parse_args()
    reference_date = date.fromisoformat(args.date) if args.date else None

    if args.dry_run:
        print(
            json.dumps(
                {
                    "job_type": "evening_full",
                    "dry_run": True,
                    "athlete_id": args.athlete_id,
                    "reference_date": reference_date.isoformat() if reference_date else None,
                    "force": args.force,
                },
                ensure_ascii=True,
            )
        )
        return 0

    db = SessionLocal()
    try:
        summary = run_evening_full_job(
            db,
            reference_date=reference_date,
            athlete_id=args.athlete_id,
            force=args.force,
        )
    finally:
        db.close()

    print(json.dumps(summary.to_dict(), ensure_ascii=True))
    return 1 if summary.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
