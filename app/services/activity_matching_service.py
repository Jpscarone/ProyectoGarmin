from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.garmin_activity import GarminActivity
from app.services.analysis.session_analysis_service import analyze_planned_session
from app.services.analysis_v2.session_analysis_service import run_session_analysis
from app.services.analysis_v2.weekly_analysis_service import trigger_weekly_analysis
from app.services.session_match_service import (
    MatchDecision,
    _activity_local_date,
    auto_match_activity,
    auto_match_unlinked_activities,
)


logger = logging.getLogger(__name__)


@dataclass
class ActivityMatchResult:
    activity_id: int
    matched: bool
    confidence: float | None = None
    method: str | None = None
    planned_session_id: int | None = None
    message: str = ""


@dataclass
class BatchMatchResult:
    processed: int
    matched: int
    unmatched: int
    messages: list[str]


def match_activity_to_plan(db: Session, activity_id: int) -> ActivityMatchResult:
    decision = auto_match_activity(db, activity_id)
    run_downstream_analyses_for_match_decision(db, decision)
    return _to_legacy_activity_result(decision)


def match_day_activities(db: Session, training_day_id: int) -> BatchMatchResult:
    from app.db.models.training_day import TrainingDay

    training_day = db.get(TrainingDay, training_day_id)
    if training_day is None:
        return BatchMatchResult(processed=0, matched=0, unmatched=0, messages=["Training day not found."])
    decision = auto_match_unlinked_activities(
        db,
        athlete_id=training_day.athlete_id,
        date_from=training_day.day_date,
        date_to=training_day.day_date,
        only_unmatched=False,
    )
    _run_batch_downstream_analyses(db, decision.decisions)
    return _to_legacy_batch_result(decision)


def match_recent_activities(db: Session, limit: int = 20) -> BatchMatchResult:
    statement = (
        select(GarminActivity)
        .options(selectinload(GarminActivity.activity_match))
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
        .limit(limit)
    )
    activities = list(db.scalars(statement).all())
    activity_ids = [activity.id for activity in activities]
    decisions: list[MatchDecision] = []
    for activity_id in activity_ids:
        decision = auto_match_activity(db, activity_id)
        decisions.append(decision)
    _run_batch_downstream_analyses(db, decisions)
    batch = _group_decisions(decisions)
    return _to_legacy_batch_result(batch)


def _run_batch_downstream_analyses(db: Session, decisions: Iterable[MatchDecision]) -> None:
    for decision in decisions:
        run_downstream_analyses_for_match_decision(db, decision)


def run_downstream_analyses_for_match_decision(db: Session, decision: MatchDecision) -> None:
    if decision.status != "matched" or decision.matched_session_id is None:
        return

    activity = db.get(GarminActivity, decision.activity_id)
    if activity is None:
        return

    try:
        logger.info(
            "Triggering classic analysis report after match activity_id=%s planned_session_id=%s",
            activity.id,
            decision.matched_session_id,
        )
        analyze_planned_session(db, decision.matched_session_id)
    except Exception:
        logger.exception(
            "Classic analysis report failed after match for activity_id=%s planned_session_id=%s",
            activity.id,
            decision.matched_session_id,
        )

    try:
        logger.info(
            "Triggering SessionAnalysis V2 after match activity_id=%s planned_session_id=%s",
            activity.id,
            decision.matched_session_id,
        )
        run_session_analysis(
            db,
            planned_session_id=decision.matched_session_id,
            activity_id=activity.id,
            trigger_source="activity_match",
        )
    except Exception:
        logger.exception(
            "Session analysis V2 failed after match for activity_id=%s planned_session_id=%s",
            activity.id,
            decision.matched_session_id,
        )

    try:
        activity_date = _activity_local_date(activity)
        if activity_date is not None:
            logger.info(
                "Triggering WeeklyAnalysis V2 after match athlete_id=%s week_reference_date=%s",
                activity.athlete_id,
                activity_date.isoformat(),
            )
            trigger_weekly_analysis(
                db,
                athlete_id=activity.athlete_id,
                reference_date=activity_date,
                trigger_source="activity_match",
            )
    except Exception:
        logger.exception(
            "Weekly analysis V2 failed after match for athlete_id=%s planned_session_id=%s activity_id=%s",
            activity.athlete_id,
            decision.matched_session_id,
            activity.id,
        )


def _group_decisions(decisions: list[MatchDecision]):
    from types import SimpleNamespace

    return SimpleNamespace(
        processed=len(decisions),
        matched=sum(1 for item in decisions if item.status == "matched"),
        candidate=sum(1 for item in decisions if item.status == "candidate"),
        ambiguous=sum(1 for item in decisions if item.status == "ambiguous"),
        unmatched=sum(1 for item in decisions if item.status == "unmatched"),
        decisions=decisions,
    )


def _to_legacy_activity_result(decision: MatchDecision) -> ActivityMatchResult:
    if decision.status == "matched":
        message = (
            f"Actividad vinculada con la sesion #{decision.matched_session_id}. "
            f"Score {decision.score:.1f}. {' '.join(decision.explanations)}"
        )
        return ActivityMatchResult(
            activity_id=decision.activity_id,
            matched=True,
            confidence=decision.confidence,
            method=decision.match_method,
            planned_session_id=decision.matched_session_id,
            message=message,
        )

    if decision.status == "ambiguous":
        message = (
            "Matching ambiguo: hay varias sesiones candidatas fuertes y no se vinculo automaticamente. "
            f"Mejor score {decision.score:.1f}."
        )
    elif decision.status == "candidate":
        message = (
            "Hay una sesion candidata razonable, pero no se vinculo automaticamente. "
            f"Score {decision.score:.1f}."
        )
    else:
        message = "No se encontro una sesion lo bastante confiable para vincular automaticamente."

    return ActivityMatchResult(
        activity_id=decision.activity_id,
        matched=False,
        confidence=decision.confidence,
        method=decision.match_method,
        planned_session_id=decision.matched_session_id,
        message=message,
    )


def _to_legacy_batch_result(batch) -> BatchMatchResult:
    messages = []
    for decision in batch.decisions:
        legacy = _to_legacy_activity_result(decision)
        messages.append(f"Activity {legacy.activity_id}: {legacy.message}")
    return BatchMatchResult(
        processed=batch.processed,
        matched=batch.matched,
        unmatched=batch.unmatched + batch.candidate + batch.ambiguous,
        messages=messages,
    )


__all__ = [
    "ActivityMatchResult",
    "BatchMatchResult",
    "_activity_local_date",
    "match_activity_to_plan",
    "match_day_activities",
    "match_recent_activities",
    "run_downstream_analyses_for_match_decision",
]
