from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import daily_health_metric  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import health_ai_analysis  # noqa: F401
from app.db.models import health_sync_state  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import session_analysis  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models import weekly_analysis  # noqa: F401
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.athlete import Athlete
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.health_ai_analysis import HealthAiAnalysis
from app.db.models.planned_session import PlannedSession
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.services.dashboard_service import build_dashboard_context, format_duration_minutes


class DashboardServiceTests(unittest.TestCase):
    def test_format_duration_minutes_humanizes_values(self) -> None:
        self.assertEqual(format_duration_minutes(45), "45 min")
        self.assertEqual(format_duration_minutes(60), "1 h")
        self.assertEqual(format_duration_minutes(75), "1 h 15 min")
        self.assertEqual(format_duration_minutes(144), "2 h 24 min")

    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        self.athlete = Athlete(name="Atleta Dashboard")
        self.db.add(self.athlete)
        self.db.commit()
        self.db.refresh(self.athlete)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_dashboard_with_no_plan_adds_no_plan_alert(self) -> None:
        context = build_dashboard_context(
            self.db,
            self.athlete,
            None,
            selected_date=date(2026, 5, 2),
        )

        self.assertTrue(any(alert["title"] == "No hay plan activo" for alert in context["alerts"]))

    def test_dashboard_includes_today_session_name(self) -> None:
        plan = self._plan()
        session = self._session(plan=plan, day_date=date(2026, 5, 2), name="Tempo controlado")

        context = build_dashboard_context(
            self.db,
            self.athlete,
            plan,
            selected_date=date(2026, 5, 2),
        )

        self.assertTrue(context["today_session"]["exists"])
        self.assertEqual(context["today_session"]["title"], session.name)

    def test_dashboard_shows_readiness_score_when_health_metric_exists(self) -> None:
        plan = self._plan()
        self._seed_health_window(reference_date=date(2026, 5, 2), sleep_minutes=480, resting_hr=50, hrv=62.0, stress=20, body_battery=75)

        context = build_dashboard_context(
            self.db,
            self.athlete,
            plan,
            selected_date=date(2026, 5, 2),
        )

        self.assertIsNotNone(context["health"]["readiness_score"])
        self.assertIsNotNone(context["today_status"]["score"])

    def test_dashboard_shows_activity_of_today(self) -> None:
        plan = self._plan()
        self._activity(
            start_time=datetime(2026, 5, 2, 8, 0, tzinfo=timezone.utc),
            activity_name="Rodaje del dia",
            avg_hr=146,
            training_load=132,
        )

        context = build_dashboard_context(
            self.db,
            self.athlete,
            plan,
            selected_date=date(2026, 5, 2),
        )

        self.assertTrue(context["today_activity"]["exists"])
        self.assertEqual(context["today_activity"]["title"], "Rodaje del dia")
        self.assertEqual(context["today_status"]["headline"], "Actividad realizada, análisis pendiente")
        self.assertIn("FC media 146 ppm", context["today_activity"]["summary"])
        self.assertIn("Load 132", context["today_activity"]["summary"])
        self.assertTrue(context["today_status"]["decision"])

    def test_dashboard_adds_intensity_alert_for_low_readiness_and_hard_session(self) -> None:
        plan = self._plan()
        self._session(plan=plan, day_date=date(2026, 5, 2), name="Series 6x1000", session_type="intervals", is_key_session=True)
        self._seed_health_window(reference_date=date(2026, 5, 2), sleep_minutes=300, resting_hr=60, hrv=35.0, stress=70, body_battery=25)

        context = build_dashboard_context(
            self.db,
            self.athlete,
            plan,
            selected_date=date(2026, 5, 2),
        )

        self.assertTrue(any(alert["title"] == "Cuidado con la intensidad" for alert in context["alerts"]))
        self.assertEqual(len(context["critical_alerts"]), 1)

    def test_dashboard_detects_today_activity_analysis(self) -> None:
        plan = self._plan()
        session = self._session(plan=plan, day_date=date(2026, 5, 2), name="Fondo")
        activity = self._activity(
            start_time=datetime(2026, 5, 2, 8, 0, tzinfo=timezone.utc),
            activity_name="Rodaje analizado",
            avg_hr=146,
            training_load=150,
        )
        self.db.add(
            ActivitySessionMatch(
                athlete_id=self.athlete.id,
                garmin_activity_id_fk=activity.id,
                planned_session_id_fk=session.id,
                training_day_id_fk=session.training_day_id,
                match_confidence=0.95,
                match_method="auto",
            )
        )
        self.db.add(
            SessionAnalysis(
                athlete_id=self.athlete.id,
                planned_session_id=session.id,
                activity_id=activity.id,
                status="completed",
                analysis_version="v2",
                execution_score=84,
            )
        )
        self.db.commit()

        context = build_dashboard_context(
            self.db,
            self.athlete,
            plan,
            selected_date=date(2026, 5, 2),
        )

        self.assertTrue(context["today_activity"]["has_analysis"])
        self.assertEqual(context["today_status"]["headline"], "Actividad realizada y analizada")
        self.assertIn("Score 84%", context["today_status"]["summary"])
        self.assertIn("Vinculada a Fondo", context["today_activity"]["summary"])
        self.assertIn("Analizada", context["today_activity"]["summary"])
        self.assertEqual(context["today_session"]["status_badges"], ["Realizada", "Analizada"])

    def test_dashboard_pending_session_recommendation_depends_on_readiness(self) -> None:
        plan = self._plan()
        self._session(plan=plan, day_date=date(2026, 5, 2), name="Tempo controlado", session_type="tempo")
        self._seed_health_window(reference_date=date(2026, 5, 2), sleep_minutes=480, resting_hr=50, hrv=62.0, stress=20, body_battery=75)

        context = build_dashboard_context(
            self.db,
            self.athlete,
            plan,
            selected_date=date(2026, 5, 2),
        )

        self.assertEqual(context["today_status"]["headline"], "Sesión pendiente para hoy")
        self.assertIn("Podés hacer la sesión normal.", context["today_status"]["recommendation"])
        self.assertEqual(context["today_session"]["status_badges"], ["Pendiente"])
        self.assertEqual(context["today_status"]["decision"], "Hacer la sesión como está planificada.")

    def test_dashboard_day_without_session_focuses_on_recovery(self) -> None:
        plan = self._plan()
        self._seed_health_window(reference_date=date(2026, 5, 2), sleep_minutes=450, resting_hr=52, hrv=58.0, stress=28, body_battery=60)

        context = build_dashboard_context(
            self.db,
            self.athlete,
            plan,
            selected_date=date(2026, 5, 2),
        )

        self.assertEqual(context["today_status"]["headline"], "Día sin sesión planificada")
        self.assertIn("recuperación o movilidad suave", context["today_status"]["recommendation"].lower())

    def test_dashboard_health_summary_is_short(self) -> None:
        plan = self._plan()
        self._seed_health_window(reference_date=date(2026, 5, 2), sleep_minutes=450, resting_hr=52, hrv=58.0, stress=28, body_battery=60)
        self.db.add(
            HealthAiAnalysis(
                athlete_id=self.athlete.id,
                reference_date=date(2026, 5, 2),
                summary=(
                    "Readiness alto. Sueno aceptable y HRV estable para hoy. "
                    "El Body Battery viene algo mas bajo de lo ideal. "
                    "No hace falta agregar carga extra."
                ),
                training_recommendation="Mantener control.",
            )
        )
        self.db.commit()

        context = build_dashboard_context(
            self.db,
            self.athlete,
            plan,
            selected_date=date(2026, 5, 2),
        )

        summary = context["health"]["dashboard_summary"]
        self.assertLessEqual(len(summary), 170)
        self.assertLessEqual(summary.count("."), 2)

    def test_dashboard_marks_unlinked_activity_on_today_session(self) -> None:
        plan = self._plan()
        self._session(plan=plan, day_date=date(2026, 5, 2), name="Fondo corto")
        self._activity(start_time=datetime(2026, 5, 2, 8, 0, tzinfo=timezone.utc), activity_name="Rodaje libre")

        context = build_dashboard_context(
            self.db,
            self.athlete,
            plan,
            selected_date=date(2026, 5, 2),
        )

        self.assertIn("Actividad sin vincular", context["today_session"]["status_badges"])
        self.assertEqual(context["today_activity"]["link_status_label"], "Sin vincular")

    def test_dashboard_uses_specific_decision_when_next_session_is_smooth(self) -> None:
        plan = self._plan()
        today_session = self._session(plan=plan, day_date=date(2026, 5, 2), name="Fondo controlado", session_type="tempo")
        activity = self._activity(
            start_time=datetime(2026, 5, 2, 8, 0, tzinfo=timezone.utc),
            activity_name="Rodaje base",
            avg_hr=140,
            training_load=180,
        )
        self.db.add(
            ActivitySessionMatch(
                athlete_id=self.athlete.id,
                garmin_activity_id_fk=activity.id,
                planned_session_id_fk=today_session.id,
                training_day_id_fk=today_session.training_day_id,
                match_confidence=0.95,
                match_method="auto",
            )
        )
        self.db.add(
            SessionAnalysis(
                athlete_id=self.athlete.id,
                planned_session_id=today_session.id,
                activity_id=activity.id,
                status="completed",
                analysis_version="v2",
                execution_score=90,
            )
        )
        self._session(plan=plan, day_date=date(2026, 5, 3), name="Regenerativo", session_type="easy")
        self._seed_health_window(reference_date=date(2026, 5, 2), sleep_minutes=420, resting_hr=54, hrv=52.0, stress=32, body_battery=58)
        self.db.commit()

        context = build_dashboard_context(
            self.db,
            self.athlete,
            plan,
            selected_date=date(2026, 5, 2),
        )

        self.assertEqual(
            context["today_status"]["decision"],
            "Mantener la próxima sesión suave y no sumar intensidad extra.",
        )

    def test_dashboard_weekly_duration_uses_human_label(self) -> None:
        plan = self._plan()
        self._activity(start_time=datetime(2026, 4, 28, 8, 0, tzinfo=timezone.utc), activity_name="A1")
        self._activity(start_time=datetime(2026, 4, 30, 8, 0, tzinfo=timezone.utc), activity_name="A2")
        self._activity(start_time=datetime(2026, 5, 2, 8, 0, tzinfo=timezone.utc), activity_name="A3")
        activities = self.db.query(GarminActivity).all()
        for activity in activities:
            activity.duration_sec = 48 * 60
        self.db.commit()

        context = build_dashboard_context(
            self.db,
            self.athlete,
            plan,
            selected_date=date(2026, 5, 2),
        )

        self.assertEqual(context["weekly_summary"]["total_duration_minutes"], 144)
        self.assertEqual(context["weekly_summary"]["total_duration_label"], "2 h 24 min")

    def test_dashboard_weekly_summary_stays_short(self) -> None:
        plan = self._plan()
        self._activity(start_time=datetime(2026, 4, 28, 8, 0, tzinfo=timezone.utc), activity_name="A1")
        self._session(plan=plan, day_date=date(2026, 4, 28), name="Rodaje")

        context = build_dashboard_context(
            self.db,
            self.athlete,
            plan,
            selected_date=date(2026, 5, 2),
        )

        self.assertLessEqual(len(context["weekly_summary"]["summary"]), 130)

    def _plan(self) -> TrainingPlan:
        plan = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan Base",
            sport_type="running",
            start_date=date(2026, 4, 28),
            end_date=date(2026, 6, 1),
            status="active",
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def _session(
        self,
        *,
        plan: TrainingPlan,
        day_date: date,
        name: str,
        session_type: str = "easy",
        is_key_session: bool = False,
    ) -> PlannedSession:
        day = TrainingDay(
            training_plan_id=plan.id,
            athlete_id=self.athlete.id,
            day_date=day_date,
            day_type="train",
        )
        self.db.add(day)
        self.db.flush()
        session = PlannedSession(
            training_day_id=day.id,
            athlete_id=self.athlete.id,
            sport_type="running",
            name=name,
            session_type=session_type,
            expected_duration_min=60,
            target_notes="ritmo controlado",
            is_key_session=is_key_session,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def _activity(
        self,
        *,
        start_time: datetime,
        activity_name: str,
        avg_hr: int | None = None,
        training_load: float | None = None,
    ) -> GarminActivity:
        activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=int(start_time.timestamp()),
            activity_name=activity_name,
            sport_type="running",
            start_time=start_time,
            duration_sec=3600,
            distance_m=12000,
            avg_hr=avg_hr,
            training_load=training_load,
            is_multisport=False,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)
        return activity

    def _seed_health_window(
        self,
        *,
        reference_date: date,
        sleep_minutes: int,
        resting_hr: int,
        hrv: float,
        stress: int,
        body_battery: int,
    ) -> None:
        for offset in range(14):
            metric_date = reference_date - timedelta(days=offset)
            self.db.add(
                DailyHealthMetric(
                    athlete_id=self.athlete.id,
                    metric_date=metric_date,
                    sleep_duration_minutes=sleep_minutes,
                    sleep_hours=round(sleep_minutes / 60, 2),
                    resting_hr=resting_hr,
                    hrv_value=hrv,
                    stress_avg=stress,
                    body_battery_morning=body_battery,
                    source="garmin",
                )
            )
        self.db.commit()


if __name__ == "__main__":
    unittest.main()
