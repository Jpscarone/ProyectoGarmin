from __future__ import annotations

import json
import unittest
from datetime import date, datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import analysis_report  # noqa: F401
from app.db.models import analysis_report_item  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import garmin_activity_lap  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import planned_session_step  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.athlete import Athlete
from app.db.models.garmin_activity import GarminActivity
from app.db.models.garmin_activity_lap import GarminActivityLap
from app.db.models.planned_session import PlannedSession
from app.db.models.planned_session_step import PlannedSessionStep
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.services.analysis.session_analysis_service import analyze_planned_session


class SessionAnalysisServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        athlete_row = Athlete(name="Atleta Analisis", max_hr=190)
        self.db.add(athlete_row)
        self.db.commit()
        self.db.refresh(athlete_row)
        self.athlete = athlete_row

        training_plan_row = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan Analisis",
            sport_type="running",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            status="active",
        )
        self.db.add(training_plan_row)
        self.db.commit()
        self.db.refresh(training_plan_row)
        self.training_plan = training_plan_row

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_analyze_planned_session_requires_linked_activity(self) -> None:
        planned_session_row = self._create_session(
            session_date=date(2026, 4, 5),
            name="Rodaje sin actividad",
            expected_duration_min=50,
            expected_distance_km=8.0,
        )

        with self.assertRaises(ValueError) as context:
            analyze_planned_session(self.db, planned_session_row.id)

        self.assertIn("actividad vinculada", str(context.exception).lower())

    def test_analyze_planned_session_generates_report_and_ai_conclusion(self) -> None:
        planned_session_row = self._create_session(
            session_date=date(2026, 4, 5),
            name="Rodaje Z2",
            expected_duration_min=60,
            expected_distance_km=10.0,
        )
        activity = self._link_activity(
            planned_session_row,
            garmin_activity_id=7001,
            duration_sec=3540,
            distance_m=9800,
            avg_hr=146,
            max_hr=160,
            avg_pace_sec_km=361.0,
        )
        self._add_lap(activity, lap_number=1, duration_sec=3540, distance_m=9800, avg_hr=146, avg_pace_sec_km=361.0)

        with patch(
            "app.services.analysis.session_analysis_service.generate_text_analysis",
            return_value="Sesion bien ejecutada, con pequenos desvios pero dentro de lo esperado. Mantener el control de intensidad en la proxima salida.",
        ):
            report = analyze_planned_session(self.db, planned_session_row.id)

        self.assertIsNotNone(report.id)
        self.assertEqual(report.planned_session_id, planned_session_row.id)
        self.assertEqual(
            report.final_conclusion_text,
            "Sesion bien ejecutada, con pequenos desvios pero dentro de lo esperado. Mantener el control de intensidad en la proxima salida.",
        )
        self.assertIsNotNone(report.overall_score)

        context = json.loads(report.analysis_context_json or "{}")
        self.assertIn("structured_summary", context)
        self.assertEqual(context["structured_summary"]["sport"]["match"], True)
        self.assertEqual(context["structured_summary"]["blocks"]["matched_count"], 0)

    def test_analyze_planned_session_stores_clear_differences(self) -> None:
        planned_session_row = self._create_session(
            session_date=date(2026, 4, 6),
            name="Fondo progresivo",
            expected_duration_min=60,
            expected_distance_km=10.0,
            expected_elevation_gain_m=120.0,
        )
        activity = self._link_activity(
            planned_session_row,
            garmin_activity_id=7002,
            duration_sec=1800,
            distance_m=5000,
            elevation_gain_m=20.0,
            avg_hr=170,
            max_hr=182,
            avg_pace_sec_km=420.0,
        )
        self._add_lap(activity, lap_number=1, duration_sec=1800, distance_m=5000, avg_hr=170, avg_pace_sec_km=420.0)

        with patch(
            "app.services.analysis.session_analysis_service.generate_text_analysis",
            return_value="Sesion claramente por debajo del objetivo previsto. Conviene revisar carga y ejecutar la proxima sesion con mejor control.",
        ):
            report = analyze_planned_session(self.db, planned_session_row.id)

        context = json.loads(report.analysis_context_json or "{}")
        deltas = context["structured_summary"]["planned_vs_actual"]
        self.assertEqual(deltas["duration"]["difference_pct"], -50.0)
        self.assertEqual(deltas["distance"]["difference_pct"], -50.0)
        self.assertAlmostEqual(deltas["elevation"]["difference_pct"], -83.3, places=1)
        self.assertEqual(context["structured_summary"]["result_status"], "failed")

    def _create_session(
        self,
        *,
        session_date: date,
        name: str,
        expected_duration_min: int | None = None,
        expected_distance_km: float | None = None,
        expected_elevation_gain_m: float | None = None,
    ) -> PlannedSession:
        training_day_row = TrainingDay(
            training_plan_id=self.training_plan.id,
            athlete_id=self.athlete.id,
            day_date=session_date,
        )
        self.db.add(training_day_row)
        self.db.commit()
        self.db.refresh(training_day_row)

        planned_session_row = PlannedSession(
            training_day_id=training_day_row.id,
            athlete_id=self.athlete.id,
            sport_type="running",
            name=name,
            session_order=1,
            expected_duration_min=expected_duration_min,
            expected_distance_km=expected_distance_km,
            expected_elevation_gain_m=expected_elevation_gain_m,
            target_hr_zone="Z2",
            target_notes="rodaje controlado",
        )
        self.db.add(planned_session_row)
        self.db.commit()
        self.db.refresh(planned_session_row)
        return planned_session_row

    def _link_activity(
        self,
        planned_session_row: PlannedSession,
        *,
        garmin_activity_id: int,
        duration_sec: int | None,
        distance_m: float | None,
        elevation_gain_m: float | None = None,
        avg_hr: int | None = None,
        max_hr: int | None = None,
        avg_pace_sec_km: float | None = None,
    ) -> GarminActivity:
        activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=garmin_activity_id,
            activity_name=f"Actividad {garmin_activity_id}",
            sport_type="running",
            start_time=datetime.combine(planned_session_row.training_day.day_date, datetime.min.time()),
            duration_sec=duration_sec,
            distance_m=distance_m,
            elevation_gain_m=elevation_gain_m,
            avg_hr=avg_hr,
            max_hr=max_hr,
            avg_pace_sec_km=avg_pace_sec_km,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)

        match = ActivitySessionMatch(
            athlete_id=self.athlete.id,
            garmin_activity_id_fk=activity.id,
            planned_session_id_fk=planned_session_row.id,
            training_day_id_fk=planned_session_row.training_day_id,
            match_confidence=0.9,
            match_method="manual",
            match_notes="test",
        )
        self.db.add(match)
        self.db.commit()
        self.db.refresh(activity)
        self.db.refresh(planned_session_row)
        return activity

    def _add_lap(
        self,
        activity: GarminActivity,
        *,
        lap_number: int,
        duration_sec: int | None,
        distance_m: float | None,
        avg_hr: int | None,
        avg_pace_sec_km: float | None,
    ) -> None:
        lap = GarminActivityLap(
            garmin_activity_id_fk=activity.id,
            lap_number=lap_number,
            duration_sec=duration_sec,
            distance_m=distance_m,
            avg_hr=avg_hr,
            avg_pace_sec_km=avg_pace_sec_km,
        )
        self.db.add(lap)
        self.db.commit()


if __name__ == "__main__":
    unittest.main()
