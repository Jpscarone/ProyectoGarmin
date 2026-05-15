from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as app_main
from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import analysis_report  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import goal  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import planned_session_step  # noqa: F401
from app.db.models import session_group  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models import user  # noqa: F401
from app.db.models import user_athlete_permission  # noqa: F401
from app.db.models.analysis_report import AnalysisReport
from app.db.models.athlete import Athlete
from app.db.models.garmin_activity import GarminActivity
from app.db.models.goal import Goal
from app.db.models.planned_session import PlannedSession
from app.db.models.planned_session_step import PlannedSessionStep
from app.db.models.session_group import SessionGroup
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.models.user import User
from app.db.models.user_athlete_permission import UserAthletePermission
from app.db.session import get_db
from app.main import app
from app.services.security import hash_password


class MultiuserRouteHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.middleware_session_local = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.original_session_local = app_main.SessionLocal
        app_main.SessionLocal = self.middleware_session_local

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app, raise_server_exceptions=False)

        self.athlete_a = self._athlete("Pablo")
        self.athlete_b = self._athlete("Lucia")
        self.plan_a = self._plan(self.athlete_a.id, "Plan A")
        self.plan_b = self._plan(self.athlete_b.id, "Plan B")
        self.day_a = self._day(self.plan_a.id, self.athlete_a.id, date(2026, 5, 10))
        self.day_b = self._day(self.plan_b.id, self.athlete_b.id, date(2026, 5, 10))
        self.group_a = self._group(self.day_a.id, "Grupo A")
        self.group_b = self._group(self.day_b.id, "Grupo B")
        self.session_a = self._session(self.day_a.id, self.athlete_a.id, self.group_a.id, "Sesion A")
        self.session_b = self._session(self.day_b.id, self.athlete_b.id, self.group_b.id, "Sesion B")
        self.step_a = self._step(self.session_a.id)
        self.step_b = self._step(self.session_b.id)
        self.goal_a = self._goal(self.athlete_a.id, self.plan_a.id, "Objetivo A")
        self.goal_b = self._goal(self.athlete_b.id, self.plan_b.id, "Objetivo B")
        self.activity_a = self._activity(self.athlete_a.id, 1001, "Actividad A")
        self.activity_b = self._activity(self.athlete_b.id, 2001, "Actividad B")
        self.report_b = self._report(self.athlete_b.id, self.day_b.id, self.session_b.id, self.activity_b.id, "Reporte B")

        self.admin = self._user("admin@example.com", "Admin", "admin")
        self.coach = self._user("coach@example.com", "Coach", "coach")
        self.user_a = self._user("a@example.com", "User A", "athlete")
        self.user_b = self._user("b@example.com", "User B", "athlete")
        self.viewer = self._user("viewer@example.com", "Viewer", "athlete")

        self._permission(self.coach.id, self.athlete_a.id, "coach", True, True, True)
        self._permission(self.user_a.id, self.athlete_a.id, "owner", True, True, True)
        self._permission(self.user_b.id, self.athlete_b.id, "owner", True, True, True)
        self._permission(self.viewer.id, self.athlete_a.id, "viewer", True, False, False)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app_main.SessionLocal = self.original_session_local
        self.db.close()
        self.engine.dispose()

    def test_user_a_cannot_read_edit_or_delete_session_group_of_user_b(self) -> None:
        self._login_cookie(self.user_a.id, self.athlete_a.id)

        read_response = self.client.get(f"/session_groups/{self.group_b.id}")
        update_response = self.client.put(f"/session_groups/{self.group_b.id}", json={"name": "Hack"})
        delete_response = self.client.delete(f"/session_groups/{self.group_b.id}")

        self.assertEqual(read_response.status_code, 403)
        self.assertEqual(update_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)

    def test_user_a_cannot_create_step_in_session_of_user_b(self) -> None:
        self._login_cookie(self.user_a.id, self.athlete_a.id)

        response = self.client.post(
            "/planned_session_steps",
            json={
                "planned_session_id": self.session_b.id,
                "step_order": 1,
                "step_type": "steady",
                "duration_sec": 600,
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_user_a_cannot_edit_or_delete_step_of_user_b(self) -> None:
        self._login_cookie(self.user_a.id, self.athlete_a.id)

        update_response = self.client.put(
            f"/planned_session_steps/{self.step_b.id}",
            json={"duration_sec": 900},
        )
        delete_response = self.client.delete(f"/planned_session_steps/{self.step_b.id}")

        self.assertEqual(update_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)

    def test_goals_list_only_shows_permitted_goals(self) -> None:
        self._login_cookie(self.user_a.id, self.athlete_a.id)

        response = self.client.get("/goals")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["name"] for item in payload], ["Objetivo A"])

    def test_user_a_cannot_open_edit_or_delete_goal_of_user_b(self) -> None:
        self._login_cookie(self.user_a.id, self.athlete_a.id)

        read_response = self.client.get(f"/goals/{self.goal_b.id}")
        update_response = self.client.put(f"/goals/{self.goal_b.id}", json={"name": "Nope"})
        delete_response = self.client.delete(f"/goals/{self.goal_b.id}")

        self.assertEqual(read_response.status_code, 403)
        self.assertEqual(update_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)

    def test_user_a_cannot_create_goal_for_unpermitted_athlete(self) -> None:
        self._login_cookie(self.user_a.id, self.athlete_a.id)

        response = self.client.post(
            "/goals",
            json={"athlete_id": self.athlete_b.id, "training_plan_id": self.plan_b.id, "name": "Intruso"},
        )

        self.assertEqual(response.status_code, 403)

    def test_user_a_cannot_link_own_activity_with_session_of_other_athlete(self) -> None:
        self._login_cookie(self.user_a.id, self.athlete_a.id)

        response = self.client.post(
            f"/activities/{self.activity_a.id}/link-session",
            json={"planned_session_id": self.session_b.id},
        )

        self.assertEqual(response.status_code, 403)

    def test_user_a_cannot_link_activity_of_other_athlete_with_own_session(self) -> None:
        self._login_cookie(self.user_a.id, self.athlete_a.id)

        response = self.client.post(
            f"/activities/{self.activity_b.id}/manual-match",
            data={"planned_session_id": self.session_a.id},
        )

        self.assertEqual(response.status_code, 403)

    def test_user_a_cannot_get_analysis_bundles_of_other_athlete(self) -> None:
        self._login_cookie(self.user_a.id, self.athlete_a.id)

        urls = [
            f"/analysis/bundle/activity/{self.activity_b.id}",
            f"/analysis/bundle/session/{self.session_b.id}",
            f"/analysis/bundle/report/{self.report_b.id}",
        ]

        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, url)

    def test_user_without_can_sync_garmin_cannot_resolve_pending(self) -> None:
        self._login_cookie(self.viewer.id, self.athlete_a.id)

        response = self.client.post("/sync/garmin/resolve-pending", follow_redirects=False)

        self.assertEqual(response.status_code, 403)

    def test_coach_only_operates_on_assigned_athletes(self) -> None:
        self._login_cookie(self.coach.id, self.athlete_a.id)

        allowed_response = self.client.get(f"/session_groups/{self.group_a.id}")
        denied_response = self.client.get(f"/session_groups/{self.group_b.id}")

        self.assertEqual(allowed_response.status_code, 200)
        self.assertEqual(denied_response.status_code, 403)

    def test_admin_can_operate_on_all_athletes(self) -> None:
        self._login_cookie(self.admin.id, self.athlete_a.id)

        group_response = self.client.get(f"/session_groups/{self.group_b.id}")
        goal_response = self.client.post(
            "/goals",
            json={"athlete_id": self.athlete_b.id, "training_plan_id": self.plan_b.id, "name": "Objetivo admin"},
        )

        self.assertEqual(group_response.status_code, 200)
        self.assertEqual(goal_response.status_code, 201)

    def _login_cookie(self, user_id: int, athlete_id: int | None = None) -> None:
        parts = [f"current_user_id:{user_id}"]
        if athlete_id is not None:
            parts.append(f"current_athlete_id:{athlete_id}")
        self.client.cookies.set("training_app_context", "|".join(parts))

    def _athlete(self, name: str) -> Athlete:
        athlete = Athlete(name=name, status="active")
        self.db.add(athlete)
        self.db.commit()
        self.db.refresh(athlete)
        return athlete

    def _plan(self, athlete_id: int, name: str) -> TrainingPlan:
        plan = TrainingPlan(
            athlete_id=athlete_id,
            name=name,
            sport_type="running",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 6, 1),
            status="active",
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def _day(self, training_plan_id: int, athlete_id: int, day_date: date) -> TrainingDay:
        row = TrainingDay(
            training_plan_id=training_plan_id,
            athlete_id=athlete_id,
            day_date=day_date,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _group(self, training_day_id: int, name: str) -> SessionGroup:
        row = SessionGroup(training_day_id=training_day_id, name=name, group_order=1)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _session(self, training_day_id: int, athlete_id: int, session_group_id: int, name: str) -> PlannedSession:
        row = PlannedSession(
            training_day_id=training_day_id,
            athlete_id=athlete_id,
            session_group_id=session_group_id,
            name=name,
            sport_type="running",
            session_order=1,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _step(self, planned_session_id: int) -> PlannedSessionStep:
        row = PlannedSessionStep(
            planned_session_id=planned_session_id,
            step_order=1,
            step_type="steady",
            duration_sec=600,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _goal(self, athlete_id: int, training_plan_id: int, name: str) -> Goal:
        row = Goal(
            athlete_id=athlete_id,
            training_plan_id=training_plan_id,
            name=name,
            sport_type="running",
            event_date=date(2026, 6, 15),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _activity(self, athlete_id: int, garmin_activity_id: int, activity_name: str) -> GarminActivity:
        row = GarminActivity(
            athlete_id=athlete_id,
            garmin_activity_id=garmin_activity_id,
            activity_name=activity_name,
            sport_type="running",
            start_time=datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
            duration_sec=3600,
            distance_m=10000,
            is_multisport=False,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _report(
        self,
        athlete_id: int,
        training_day_id: int,
        planned_session_id: int,
        activity_id: int,
        title: str,
    ) -> AnalysisReport:
        row = AnalysisReport(
            athlete_id=athlete_id,
            report_type="session",
            training_day_id=training_day_id,
            planned_session_id=planned_session_id,
            garmin_activity_id_fk=activity_id,
            title=title,
            overall_status="correct",
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _user(self, email: str, name: str, role: str) -> User:
        user = User(
            email=email,
            name=name,
            password_hash=hash_password("secret123"),
            role=role,
            is_active=True,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def _permission(
        self,
        user_id: int,
        athlete_id: int,
        permission_role: str,
        can_view: bool,
        can_edit: bool,
        can_sync_garmin: bool,
    ) -> None:
        row = UserAthletePermission(
            user_id=user_id,
            athlete_id=athlete_id,
            permission_role=permission_role,
            can_view=can_view,
            can_edit=can_edit,
            can_sync_garmin=can_sync_garmin,
        )
        self.db.add(row)
        self.db.commit()


if __name__ == "__main__":
    unittest.main()
