from __future__ import annotations

import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models.athlete import Athlete
from app.services.athlete_zone_service import recalculate_athlete_zones, update_athlete_zones_manual, use_garmin_zones
from app.services.garmin.profile_sync import apply_garmin_changes, build_athlete_garmin_comparison


class AthleteGarminProfileSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_build_comparison_detects_general_and_zone_differences(self) -> None:
        athlete_row = Athlete(
            name="Atleta Garmin",
            max_hr=180,
            vo2max=52.0,
            hr_zones_json=json.dumps({"running": [{"name": "Z1", "min": 100, "max": 120}]}),
            garmin_profile_snapshot_json=json.dumps(
                {
                    "general": {"max_hr": 182, "vo2max": 53.0},
                    "hr_zones": {"running": [{"name": "Z1", "min": 102, "max": 122}]},
                    "power_zones": {},
                }
            ),
        )
        self.db.add(athlete_row)
        self.db.commit()

        comparison = build_athlete_garmin_comparison(athlete_row)

        self.assertTrue(comparison["has_differences"])
        self.assertTrue(comparison["has_general_differences"])
        self.assertTrue(comparison["has_hr_zone_differences"])
        self.assertEqual(comparison["general_rows"][0]["label"], "FC maxima")
        self.assertEqual(comparison["hr_zone_rows"][0]["garmin_value"], "102 - 122")

    def test_apply_garmin_changes_updates_only_selected_block(self) -> None:
        athlete_row = Athlete(
            name="Atleta Garmin",
            max_hr=180,
            vo2max=50.0,
            hr_zones_json=json.dumps({"running": [{"name": "Z1", "min": 100, "max": 120}]}),
            garmin_profile_snapshot_json=json.dumps(
                {
                    "general": {"max_hr": 182, "vo2max": 53.0},
                    "hr_zones": {"running": [{"name": "Z1", "min": 102, "max": 122}]},
                    "power_zones": {},
                }
            ),
        )
        self.db.add(athlete_row)
        self.db.commit()

        applied = apply_garmin_changes(self.db, athlete_row, "general")

        self.assertIn("datos generales", applied)
        self.assertEqual(athlete_row.max_hr, 182)
        self.assertEqual(athlete_row.vo2max, 53.0)
        self.assertEqual(json.loads(athlete_row.hr_zones_json)["running"][0]["min"], 100)

    def test_apply_garmin_changes_updates_zone_block_without_clearing_other_values(self) -> None:
        athlete_row = Athlete(
            name="Atleta Garmin",
            max_hr=180,
            hr_zones_json=json.dumps({"running": [{"name": "Z1", "min": 100, "max": 120}]}),
            garmin_profile_snapshot_json=json.dumps(
                {
                    "general": {"max_hr": 182},
                    "hr_zones": {"running": [{"name": "Z1", "min": 105, "max": 125}]},
                    "power_zones": {},
                }
            ),
        )
        self.db.add(athlete_row)
        self.db.commit()

        applied = apply_garmin_changes(self.db, athlete_row, "hr_zones")

        self.assertIn("zonas de frecuencia cardiaca", applied)
        self.assertEqual(athlete_row.max_hr, 180)
        self.assertEqual(json.loads(athlete_row.hr_zones_json)["running"][0]["max"], 125)

    def test_manual_zone_update_sets_manual_source(self) -> None:
        athlete_row = Athlete(name="Atleta zonas")
        self.db.add(athlete_row)
        self.db.commit()

        updated = update_athlete_zones_manual(
            self.db,
            athlete_row,
            hr_rows=[{"min": 100, "max": 120}, {"min": 121, "max": 140}, {"min": None, "max": None}, {"min": None, "max": None}, {"min": None, "max": None}],
            power_rows=[{"min": 120, "max": 180}, {"min": 181, "max": 220}, {"min": None, "max": None}, {"min": None, "max": None}, {"min": None, "max": None}],
        )

        self.assertIn("zonas de frecuencia cardiaca", updated)
        self.assertEqual(athlete_row.source_hr_zones, "manual")
        self.assertEqual(athlete_row.source_power_zones, "manual")

    def test_recalculate_zones_sets_calculated_source(self) -> None:
        athlete_row = Athlete(name="Atleta zonas", max_hr=190, cycling_ftp=300)
        self.db.add(athlete_row)
        self.db.commit()

        updated = recalculate_athlete_zones(self.db, athlete_row)

        self.assertIn("zonas de frecuencia cardiaca", updated)
        self.assertIn("zonas de potencia", updated)
        self.assertEqual(athlete_row.source_hr_zones, "calculated")
        self.assertEqual(athlete_row.source_power_zones, "calculated")
        self.assertTrue(json.loads(athlete_row.hr_zones_json)["general"])

    def test_use_garmin_zones_sets_garmin_source(self) -> None:
        athlete_row = Athlete(
            name="Atleta zonas",
            garmin_profile_snapshot_json=json.dumps(
                {
                    "general": {},
                    "hr_zones": {"general": [{"name": "Z1", "min": 100, "max": 120}]},
                    "power_zones": {"general": [{"name": "Z1", "min": 150, "max": 200}]},
                }
            ),
        )
        self.db.add(athlete_row)
        self.db.commit()

        updated = use_garmin_zones(self.db, athlete_row)

        self.assertIn("zonas de frecuencia cardiaca", updated)
        self.assertEqual(athlete_row.source_hr_zones, "garmin")
        self.assertEqual(athlete_row.source_power_zones, "garmin")


if __name__ == "__main__":
    unittest.main()
