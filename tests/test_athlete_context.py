from __future__ import annotations

import unittest
from datetime import date

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.training_plan import TrainingPlan
from app.services.athlete_context import (
    CURRENT_ATHLETE_SESSION_KEY,
    CURRENT_TRAINING_PLAN_SESSION_KEY,
    get_current_athlete,
    get_current_training_plan,
    set_current_athlete,
)


def _request(query_string: bytes = b"") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": query_string,
        "headers": [],
        "session": {},
    }
    return Request(scope)


class AthleteContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_single_active_athlete_is_selected_automatically(self) -> None:
        athlete_row = self._athlete("Pablo")
        request = _request()

        selected = get_current_athlete(request, self.db)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, athlete_row.id)
        self.assertEqual(request.session[CURRENT_ATHLETE_SESSION_KEY], athlete_row.id)

    def test_explicit_athlete_updates_session(self) -> None:
        first = self._athlete("Pablo")
        second = self._athlete("Felipe")
        request = _request(f"athlete_id={second.id}".encode())
        set_current_athlete(request, first.id)

        selected = get_current_athlete(request, self.db)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, second.id)
        self.assertEqual(request.session[CURRENT_ATHLETE_SESSION_KEY], second.id)

    def test_training_plan_must_belong_to_current_athlete(self) -> None:
        pablo = self._athlete("Pablo")
        felipe = self._athlete("Felipe")
        foreign_plan = self._plan(felipe.id, "Plan Felipe")
        request = _request(f"training_plan_id={foreign_plan.id}".encode())

        with self.assertRaises(Exception):
            get_current_training_plan(request, self.db, pablo, training_plan_id=foreign_plan.id, require_selected=True)

    def test_training_plan_session_is_cleared_when_changing_athlete(self) -> None:
        pablo = self._athlete("Pablo")
        felipe = self._athlete("Felipe")
        pablo_plan = self._plan(pablo.id, "Plan Pablo")
        felipe_plan = self._plan(felipe.id, "Plan Felipe")
        request = _request()
        request.session[CURRENT_TRAINING_PLAN_SESSION_KEY] = pablo_plan.id

        selected = get_current_training_plan(request, self.db, felipe)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, felipe_plan.id)
        self.assertEqual(request.session[CURRENT_TRAINING_PLAN_SESSION_KEY], felipe_plan.id)

    def _athlete(self, name: str, status: str = "active") -> Athlete:
        row = Athlete(name=name, status=status)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _plan(self, athlete_id: int, name: str) -> TrainingPlan:
        row = TrainingPlan(
            athlete_id=athlete_id,
            name=name,
            sport_type="running",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 5, 1),
            status="active",
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row


if __name__ == "__main__":
    unittest.main()
