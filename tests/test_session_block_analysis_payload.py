from __future__ import annotations

import os
import unittest
from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import analysis_report  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import athlete_access_code  # noqa: F401
from app.db.models import daily_health_metric  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import garmin_activity_lap  # noqa: F401
from app.db.models import goal  # noqa: F401
from app.db.models import health_ai_analysis  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import planned_session_step  # noqa: F401
from app.db.models import session_analysis  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models import weekly_analysis  # noqa: F401
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.athlete import Athlete
from app.db.models.athlete_access_code import AthleteAccessCode
from app.db.models.garmin_activity import GarminActivity
from app.db.models.garmin_activity_lap import GarminActivityLap
from app.db.models.planned_session import PlannedSession
from app.db.models.planned_session_step import PlannedSessionStep
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.session import get_db
from app.main import app


class SessionBlockAnalysisPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_token = os.environ.get("MCP_API_TOKEN")
        os.environ["MCP_API_TOKEN"] = "mcp-test-token"
        get_settings.cache_clear()

        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        self.athlete = Athlete(name="Atleta Bloques MCP")
        self.other_athlete = Athlete(name="Otro atleta")
        self.db.add_all([self.athlete, self.other_athlete])
        self.db.commit()
        self.db.refresh(self.athlete)
        self.db.refresh(self.other_athlete)
        self.db.add(
            AthleteAccessCode(
                athlete_id=self.athlete.id,
                access_code="BLOQUES-1234",
                label="Atleta bloques",
                is_active=True,
            )
        )
        self.db.commit()

        self.plan = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan bloques",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            status="active",
        )
        self.db.add(self.plan)
        self.db.commit()
        self.db.refresh(self.plan)

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer mcp-test-token"}

    def tearDown(self) -> None:
        if self.previous_token is None:
            os.environ.pop("MCP_API_TOKEN", None)
        else:
            os.environ["MCP_API_TOKEN"] = self.previous_token
        get_settings.cache_clear()
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def _create_training_day(self, target_date: date) -> TrainingDay:
        training_day = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            day_date=target_date,
        )
        self.db.add(training_day)
        self.db.commit()
        self.db.refresh(training_day)
        return training_day

    def _create_planned_session(
        self,
        training_day: TrainingDay,
        *,
        name: str,
        sport: str = "running",
        modality: str | None = "outdoor",
        session_type: str = "required",
        steps: list[dict] | None = None,
    ) -> PlannedSession:
        session = PlannedSession(
            athlete_id=self.athlete.id,
            training_day_id=training_day.id,
            sport_type=sport,
            modality=modality,
            name=name,
            session_type=session_type,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        for index, step in enumerate(steps or [], start=1):
            self.db.add(
                PlannedSessionStep(
                    planned_session_id=session.id,
                    step_order=index,
                    step_type=step.get("step_type", "steady"),
                    duration_sec=step.get("duration_sec"),
                    distance_m=step.get("distance_m"),
                    target_type=step.get("target_type"),
                    target_hr_min=step.get("target_hr_min"),
                    target_hr_max=step.get("target_hr_max"),
                    target_pace_min_sec_km=step.get("target_pace_min_sec_km"),
                    target_pace_max_sec_km=step.get("target_pace_max_sec_km"),
                    target_notes=step.get("target_notes"),
                )
            )
        self.db.commit()
        self.db.refresh(session)
        return session

    def _create_activity(
        self,
        target_dt: datetime,
        *,
        name: str = "Actividad",
        sport: str = "running",
        modality: str | None = "outdoor",
        duration_sec: int = 1800,
        distance_m: int = 5000,
        avg_hr: int | None = 145,
        max_hr: int | None = 160,
    ) -> GarminActivity:
        activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=int(target_dt.timestamp()),
            activity_name=name,
            sport_type=sport,
            modality=modality,
            start_time=target_dt,
            duration_sec=duration_sec,
            distance_m=distance_m,
            avg_hr=avg_hr,
            max_hr=max_hr,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)
        return activity

    def _add_laps(self, activity: GarminActivity, laps: list[dict]) -> None:
        for index, lap in enumerate(laps, start=1):
            self.db.add(
                GarminActivityLap(
                    garmin_activity_id_fk=activity.id,
                    lap_number=index,
                    lap_type=lap.get("lap_type", "work"),
                    duration_sec=lap.get("duration_sec"),
                    distance_m=lap.get("distance_m"),
                    avg_hr=lap.get("avg_hr"),
                    max_hr=lap.get("max_hr"),
                    avg_pace_sec_km=lap.get("avg_pace_sec_km"),
                )
            )
        self.db.commit()

    def _link_session_and_activity(self, session: PlannedSession, activity: GarminActivity, training_day: TrainingDay) -> None:
        self.db.add(
            ActivitySessionMatch(
                athlete_id=self.athlete.id,
                garmin_activity_id_fk=activity.id,
                planned_session_id_fk=session.id,
                training_day_id_fk=training_day.id,
                match_confidence=0.98,
                match_method="manual",
            )
        )
        self.db.commit()

    def test_exact_match_with_three_blocks_and_three_laps(self) -> None:
        training_day = self._create_training_day(date(2026, 5, 29))
        session = self._create_planned_session(
            training_day,
            name="Bloques controlados",
            steps=[
                {"duration_sec": 600, "target_type": "hr", "target_hr_min": 130, "target_hr_max": 140},
                {"duration_sec": 600, "target_type": "hr", "target_hr_min": 140, "target_hr_max": 150},
                {"duration_sec": 600, "target_type": "hr", "target_hr_min": 150, "target_hr_max": 160},
            ],
        )
        activity = self._create_activity(datetime(2026, 5, 29, 7, 0, 0), duration_sec=1805, distance_m=9000)
        self._add_laps(
            activity,
            [
                {"duration_sec": 602, "distance_m": 3000, "avg_hr": 136, "max_hr": 141},
                {"duration_sec": 600, "distance_m": 3000, "avg_hr": 145, "max_hr": 150},
                {"duration_sec": 603, "distance_m": 3000, "avg_hr": 155, "max_hr": 160},
            ],
        )
        self._link_session_and_activity(session, activity, training_day)

        response = self.client.get(
            f"/api/mcp/session-block-analysis-payload?athlete_id={self.athlete.id}&planned_session_id={session.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "session_block_analysis_payload_v1")
        self.assertEqual(len(payload["planned_session"]["blocks"]), 3)
        self.assertEqual(len(payload["activity_laps"]), 3)
        self.assertEqual(payload["block_matching"][0]["matched_lap_indexes"], [1])
        self.assertEqual(payload["block_matching"][0]["match_quality"], "exact")
        self.assertEqual(payload["block_matching"][0]["block_result"], "ok")
        self.assertEqual(payload["overall_block_summary"]["execution_quality"], "good")

    def test_groups_extra_laps_by_duration(self) -> None:
        training_day = self._create_training_day(date(2026, 5, 28))
        session = self._create_planned_session(
            training_day,
            name="Tres bloques",
            steps=[
                {"duration_sec": 600, "target_type": "hr", "target_hr_min": 125, "target_hr_max": 140},
                {"duration_sec": 600, "target_type": "hr", "target_hr_min": 130, "target_hr_max": 145},
                {"duration_sec": 600, "target_type": "hr", "target_hr_min": 135, "target_hr_max": 150},
            ],
        )
        activity = self._create_activity(datetime(2026, 5, 28, 7, 0, 0), duration_sec=1800, distance_m=9000)
        self._add_laps(
            activity,
            [
                {"duration_sec": 300, "distance_m": 1500, "avg_hr": 132},
                {"duration_sec": 300, "distance_m": 1500, "avg_hr": 134},
                {"duration_sec": 300, "distance_m": 1500, "avg_hr": 139},
                {"duration_sec": 300, "distance_m": 1500, "avg_hr": 141},
                {"duration_sec": 600, "distance_m": 3000, "avg_hr": 144},
            ],
        )
        self._link_session_and_activity(session, activity, training_day)

        response = self.client.get(
            f"/api/mcp/session-block-analysis-payload?athlete_id={self.athlete.id}&planned_session_id={session.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["block_matching"][0]["matched_lap_indexes"], [1, 2])
        self.assertEqual(payload["block_matching"][1]["matched_lap_indexes"], [3, 4])
        self.assertEqual(payload["block_matching"][2]["matched_lap_indexes"], [5])
        self.assertEqual(payload["block_matching"][0]["match_quality"], "estimated")

    def test_returns_limitation_when_activity_has_no_laps(self) -> None:
        training_day = self._create_training_day(date(2026, 5, 27))
        session = self._create_planned_session(
            training_day,
            name="Sin laps",
            steps=[{"duration_sec": 1200, "target_type": "hr", "target_hr_min": 130, "target_hr_max": 140}],
        )
        activity = self._create_activity(datetime(2026, 5, 27, 7, 0, 0), duration_sec=1200, distance_m=4000)
        self._link_session_and_activity(session, activity, training_day)

        response = self.client.get(
            f"/api/mcp/session-block-analysis-payload?athlete_id={self.athlete.id}&planned_session_id={session.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["activity_laps"], [])
        self.assertIn("No hay laps/splits disponibles", " ".join(payload["limitations"]))

    def test_activity_without_linked_session_returns_limitation(self) -> None:
        activity = self._create_activity(datetime(2026, 5, 26, 7, 0, 0), name="Libre", duration_sec=2200)
        self._add_laps(activity, [{"duration_sec": 2200, "distance_m": 6000, "avg_hr": 145}])

        response = self.client.get(
            f"/api/mcp/session-block-analysis-payload?athlete_id={self.athlete.id}&activity_id={activity.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["planned_session"])
        self.assertEqual(payload["activity"]["id"], activity.id)
        self.assertIn("no tiene una sesion planificada vinculada", " ".join(payload["limitations"]).lower())

    def test_ambiguous_date_returns_clear_candidates(self) -> None:
        training_day = self._create_training_day(date(2026, 5, 25))
        self._create_planned_session(training_day, name="AM running 1", steps=[{"duration_sec": 900}])
        self._create_planned_session(training_day, name="AM running 2", steps=[{"duration_sec": 900}])
        self._create_activity(datetime(2026, 5, 25, 7, 0, 0), name="Act 1")
        self._create_activity(datetime(2026, 5, 25, 18, 0, 0), name="Act 2")

        response = self.client.get(
            f"/api/mcp/session-block-analysis-payload?athlete_id={self.athlete.id}&date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertIn("No se pudo resolver", detail["message"])
        self.assertEqual(len(detail["planned_sessions"]), 2)
        self.assertEqual(len(detail["activities"]), 2)

    def test_hr_above_range_marks_slightly_high_and_too_high(self) -> None:
        training_day = self._create_training_day(date(2026, 5, 24))
        session = self._create_planned_session(
            training_day,
            name="FC alta",
            steps=[
                {"duration_sec": 600, "target_type": "hr", "target_hr_min": 130, "target_hr_max": 140},
                {"duration_sec": 600, "target_type": "hr", "target_hr_min": 130, "target_hr_max": 140},
            ],
        )
        activity = self._create_activity(datetime(2026, 5, 24, 7, 0, 0), duration_sec=1200)
        self._add_laps(
            activity,
            [
                {"duration_sec": 600, "distance_m": 2000, "avg_hr": 144, "max_hr": 146},
                {"duration_sec": 600, "distance_m": 2000, "avg_hr": 149, "max_hr": 151},
            ],
        )
        self._link_session_and_activity(session, activity, training_day)

        response = self.client.get(
            f"/api/mcp/session-block-analysis-payload?athlete_id={self.athlete.id}&planned_session_id={session.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["block_matching"][0]["block_result"], "slightly_high")
        self.assertEqual(payload["block_matching"][1]["block_result"], "too_high")

    def test_missing_hr_returns_unknown(self) -> None:
        training_day = self._create_training_day(date(2026, 5, 23))
        session = self._create_planned_session(
            training_day,
            name="Sin FC",
            steps=[{"duration_sec": 600, "target_type": "hr", "target_hr_min": 130, "target_hr_max": 140}],
        )
        activity = self._create_activity(datetime(2026, 5, 23, 7, 0, 0), duration_sec=600, avg_hr=None, max_hr=None)
        self._add_laps(activity, [{"duration_sec": 600, "distance_m": 2000, "avg_hr": None, "max_hr": None}])
        self._link_session_and_activity(session, activity, training_day)

        response = self.client.get(
            f"/api/mcp/session-block-analysis-payload?athlete_id={self.athlete.id}&planned_session_id={session.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["block_matching"][0]["block_result"], "unknown")

    def test_wrapper_access_code_resolves_same_payload(self) -> None:
        training_day = self._create_training_day(date(2026, 5, 22))
        session = self._create_planned_session(training_day, name="Wrapper", steps=[{"duration_sec": 900}])
        activity = self._create_activity(datetime(2026, 5, 22, 7, 0, 0), duration_sec=900)
        self._add_laps(activity, [{"duration_sec": 900, "distance_m": 3000, "avg_hr": 140}])
        self._link_session_and_activity(session, activity, training_day)

        response = self.client.get(
            f"/api/mcp/my/session-block-analysis-payload?access_code=BLOQUES-1234&planned_session_id={session.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["athlete"]["id"], self.athlete.id)
        self.assertEqual(payload["planned_session"]["id"], session.id)

    def test_metrics_json_pairs_drive_matching(self) -> None:
        training_day = self._create_training_day(date(2026, 5, 21))
        session = self._create_planned_session(
            training_day,
            name="Pairs",
            steps=[
                {"duration_sec": 600, "target_type": "hr", "target_hr_min": 130, "target_hr_max": 140},
                {"duration_sec": 600, "target_type": "hr", "target_hr_min": 130, "target_hr_max": 140},
            ],
        )
        activity = self._create_activity(datetime(2026, 5, 21, 7, 0, 0), duration_sec=1200)
        self._add_laps(
            activity,
            [
                {"duration_sec": 300, "distance_m": 1000, "avg_hr": 135},
                {"duration_sec": 300, "distance_m": 1000, "avg_hr": 136},
                {"duration_sec": 600, "distance_m": 2000, "avg_hr": 137},
            ],
        )
        self._link_session_and_activity(session, activity, training_day)
        self.db.add(
            SessionAnalysis(
                athlete_id=self.athlete.id,
                planned_session_id=session.id,
                activity_id=activity.id,
                status="completed",
                metrics_json={
                    "context": {"activity_laps": [{"index": 1}, {"index": 2}, {"index": 3}]},
                    "metrics": {
                        "laps": {
                            "pairs": [
                                {"planned_step_order": 1, "activity_lap_index": 1},
                                {"planned_step_order": 1, "activity_lap_index": 2},
                                {"planned_step_order": 2, "activity_lap_index": 3},
                            ]
                        }
                    },
                },
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/session-block-analysis-payload?athlete_id={self.athlete.id}&planned_session_id={session.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["block_matching"][0]["matched_lap_indexes"], [1, 2])
        self.assertEqual(payload["block_matching"][1]["matched_lap_indexes"], [3])

    def test_endpoint_does_not_modify_domain_rows(self) -> None:
        training_day = self._create_training_day(date(2026, 5, 20))
        session = self._create_planned_session(training_day, name="Read only", steps=[{"duration_sec": 900}])
        activity = self._create_activity(datetime(2026, 5, 20, 7, 0, 0), duration_sec=900)
        self._add_laps(activity, [{"duration_sec": 900, "distance_m": 3000, "avg_hr": 140}])
        self._link_session_and_activity(session, activity, training_day)

        counts_before = {
            "sessions": self.db.scalar(select(func.count()).select_from(PlannedSession)),
            "activities": self.db.scalar(select(func.count()).select_from(GarminActivity)),
            "laps": self.db.scalar(select(func.count()).select_from(GarminActivityLap)),
            "matches": self.db.scalar(select(func.count()).select_from(ActivitySessionMatch)),
        }

        response = self.client.get(
            f"/api/mcp/session-block-analysis-payload?athlete_id={self.athlete.id}&planned_session_id={session.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        counts_after = {
            "sessions": self.db.scalar(select(func.count()).select_from(PlannedSession)),
            "activities": self.db.scalar(select(func.count()).select_from(GarminActivity)),
            "laps": self.db.scalar(select(func.count()).select_from(GarminActivityLap)),
            "matches": self.db.scalar(select(func.count()).select_from(ActivitySessionMatch)),
        }
        self.assertEqual(counts_before, counts_after)


if __name__ == "__main__":
    unittest.main()
