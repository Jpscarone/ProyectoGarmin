from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import analysis_report  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import daily_health_metric  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import health_ai_analysis  # noqa: F401
from app.db.models import health_sync_state  # noqa: F401
from app.db.models import pending_training_item  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import session_analysis  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.garmin_activity import GarminActivity
from app.db.models.health_ai_analysis import HealthAiAnalysis
from app.db.models.pending_training_item import PendingTrainingItem
from app.db.models.planned_session import PlannedSession
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.services.pending_training_service import (
    ITEM_ACTIVITY_UNLINKED,
    ITEM_ACTIVITY_WITHOUT_ANALYSIS,
    ITEM_READINESS_WITHOUT_AI,
    STATUS_PENDING,
    STATUS_RESOLVED,
    create_or_update_pending_item,
    resolve_pending_item,
)
from app.services.scheduled_sync_service import SyncOperationResult


class PendingTrainingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.athlete = Athlete(name="Atleta Pending", status="active", timezone="America/Argentina/Buenos_Aires")
        self.db.add(self.athlete)
        self.db.commit()
        self.db.refresh(self.athlete)
        self.plan = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan Pending",
            sport_type="running",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            status="active",
        )
        self.db.add(self.plan)
        self.db.commit()
        self.db.refresh(self.plan)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_create_or_update_pending_item_does_not_duplicate_active_items(self) -> None:
        first, created_first = create_or_update_pending_item(
            self.db,
            athlete_id=self.athlete.id,
            item_type=ITEM_ACTIVITY_UNLINKED,
            priority="medium",
            title="Actividad sin vincular",
            message="Primera version",
            garmin_activity_id=123,
        )
        second, created_second = create_or_update_pending_item(
            self.db,
            athlete_id=self.athlete.id,
            item_type=ITEM_ACTIVITY_UNLINKED,
            priority="high",
            title="Actividad sin vincular",
            message="Mensaje actualizado",
            garmin_activity_id=123,
        )

        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.priority, "high")
        self.assertEqual(second.message, "Mensaje actualizado")
        self.assertEqual(self.db.query(PendingTrainingItem).count(), 1)

    def test_resolve_activity_without_analysis_creates_session_analysis(self) -> None:
        session = self._session(day_date=date(2026, 5, 14), name="Tempo")
        activity = self._activity(start_time=datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc), name="Rodaje")
        self._link_activity(activity, session)
        item, _ = create_or_update_pending_item(
            self.db,
            athlete_id=self.athlete.id,
            item_type=ITEM_ACTIVITY_WITHOUT_ANALYSIS,
            priority="medium",
            title="Actividad vinculada sin analisis",
            message="Falta analisis",
            garmin_activity_id=activity.id,
            planned_session_id=session.id,
        )

        def fake_run_session_analysis(db: Session, *, planned_session_id: int, activity_id: int, trigger_source: str):
            analysis = SessionAnalysis(
                athlete_id=self.athlete.id,
                planned_session_id=planned_session_id,
                activity_id=activity_id,
                status="completed",
                analysis_version="v2",
                execution_score=88,
            )
            db.add(analysis)
            db.commit()
            db.refresh(analysis)
            return analysis

        with patch("app.services.pending_training_service.run_session_analysis", side_effect=fake_run_session_analysis):
            resolved = resolve_pending_item(self.db, item.id)

        self.assertEqual(resolved.status, STATUS_RESOLVED)
        self.assertIn("analisis", resolved.message.lower())
        self.assertEqual(self.db.query(SessionAnalysis).count(), 1)

    def test_resolve_readiness_without_ai_analysis_creates_health_ai(self) -> None:
        item, _ = create_or_update_pending_item(
            self.db,
            athlete_id=self.athlete.id,
            item_type=ITEM_READINESS_WITHOUT_AI,
            priority="medium",
            title="Readiness sin IA",
            message="Falta IA",
            reference_date=date(2026, 5, 14),
        )

        def fake_generate_health_ai(db: Session, *, athlete_id: int, reference_date: date, force: bool = False):
            analysis = HealthAiAnalysis(
                athlete_id=athlete_id,
                reference_date=reference_date,
                summary="Ok",
                training_recommendation="Controlar carga",
            )
            db.add(analysis)
            db.commit()
            return SyncOperationResult(status="success", message="IA creada", health_ai_analyses_created=1)

        with patch("app.services.pending_training_service.generate_health_ai_if_needed", side_effect=fake_generate_health_ai):
            resolved = resolve_pending_item(self.db, item.id)

        self.assertEqual(resolved.status, STATUS_RESOLVED)
        self.assertEqual(self.db.query(HealthAiAnalysis).count(), 1)

    def test_resolve_activity_unlinked_keeps_pending_when_match_is_ambiguous(self) -> None:
        activity = self._activity(start_time=datetime(2026, 5, 14, 1, 30, tzinfo=timezone.utc), name="Actividad ambigua")
        item, _ = create_or_update_pending_item(
            self.db,
            athlete_id=self.athlete.id,
            item_type=ITEM_ACTIVITY_UNLINKED,
            priority="high",
            title="Actividad Garmin sin vincular",
            message="Ambigua",
            garmin_activity_id=activity.id,
        )

        preview = SimpleNamespace(status="ambiguous", score=72.0, candidate_sessions=[object(), object()])
        with patch("app.services.pending_training_service.preview_activity_match", return_value=preview):
            resolved = resolve_pending_item(self.db, item.id)

        self.assertEqual(resolved.status, STATUS_PENDING)
        self.assertIn("candidatas", resolved.message.lower())

    def _session(self, *, day_date: date, name: str) -> PlannedSession:
        day = TrainingDay(
            training_plan_id=self.plan.id,
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
            session_type="easy",
            expected_duration_min=60,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def _activity(self, *, start_time: datetime, name: str) -> GarminActivity:
        activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=int(start_time.timestamp()),
            activity_name=name,
            sport_type="running",
            start_time=start_time,
            duration_sec=3600,
            distance_m=10000,
            is_multisport=False,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)
        return activity

    def _link_activity(self, activity: GarminActivity, session: PlannedSession) -> None:
        from app.db.models.activity_session_match import ActivitySessionMatch

        match = ActivitySessionMatch(
            athlete_id=self.athlete.id,
            garmin_activity_id_fk=activity.id,
            planned_session_id_fk=session.id,
            training_day_id_fk=session.training_day_id,
            match_confidence=0.95,
            match_method="auto",
        )
        self.db.add(match)
        self.db.commit()
        self.db.refresh(activity)


if __name__ == "__main__":
    unittest.main()
