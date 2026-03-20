from __future__ import annotations

from dataclasses import dataclass
import logging
from datetime import datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay


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
    activity = _get_activity_with_context(db, activity_id)
    if activity is None:
        return ActivityMatchResult(activity_id=activity_id, matched=False, message="Activity not found.")
    if activity.start_time is None:
        _delete_existing_activity_match(db, activity)
        return ActivityMatchResult(activity_id=activity_id, matched=False, message="Activity has no start time.")

    activity_date = activity.start_time.date()
    logger.info(
        "Matching activity_id=%s athlete_id=%s activity_date=%s sport_type=%r discipline_variant=%r",
        activity.id,
        activity.athlete_id,
        activity_date.isoformat(),
        activity.sport_type,
        activity.discipline_variant,
    )

    training_day = _get_training_day_for_activity(db, activity)
    if training_day is None:
        _delete_existing_activity_match(db, activity)
        logger.info(
            "No training day found for activity_id=%s athlete_id=%s on activity_date=%s",
            activity.id,
            activity.athlete_id,
            activity_date.isoformat(),
        )
        return ActivityMatchResult(
            activity_id=activity.id,
            matched=False,
            message=(
                "No training day exists for this athlete on the activity date. "
                f"Debug: athlete_id={activity.athlete_id}, activity_date={activity_date.isoformat()}."
            ),
        )

    sessions = _ordered_sessions(training_day.planned_sessions)
    logger.info(
        "Training day found for activity_id=%s: training_day_id=%s athlete_id=%s day_date=%s planned_sessions=%s",
        activity.id,
        training_day.id,
        training_day.athlete_id,
        training_day.day_date.isoformat(),
        len(sessions),
    )

    compatibility_results = [_evaluate_sport_compatibility(activity, session) for session in sessions]
    for result in compatibility_results:
        logger.info(
            "Session candidate activity_id=%s planned_session_id=%s session_sport=%r session_variant=%r compatible=%s reason=%s",
            activity.id,
            result["session"].id,
            result["session"].sport_type,
            result["session"].discipline_variant,
            result["compatible"],
            result["reason"],
        )

    sport_candidates = [result["session"] for result in compatibility_results if result["compatible"]]
    if not sport_candidates:
        _delete_existing_activity_match(db, activity)
        candidate_debug = "; ".join(
            [
                (
                    f"session_id={result['session'].id}, "
                    f"sport={result['session'].sport_type!r}, "
                    f"variant={result['session'].discipline_variant!r}, "
                    f"reason={result['reason']}"
                )
                for result in compatibility_results
            ]
        ) or "no planned sessions"
        return ActivityMatchResult(
            activity_id=activity.id,
            matched=False,
            message=(
                "No planned session on that day matched the activity sport. "
                f"Debug: activity_id={activity.id}, athlete_id={activity.athlete_id}, activity_date={activity_date.isoformat()}, "
                f"activity_sport={activity.sport_type!r}, activity_variant={activity.discipline_variant!r}, candidates=[{candidate_debug}]"
            ),
        )

    activity_rank = _activity_rank_for_day(db, activity, training_day)
    ranked_candidates = [
        _score_candidate(activity, training_day, session, sessions, activity_rank)
        for session in sport_candidates
    ]
    ranked_candidates.sort(key=lambda item: (-item["score"], item["session"].session_order, item["session"].id))
    best = ranked_candidates[0]

    confidence = round(best["score"] / 100.0, 2)
    method = _derive_match_method(best)
    notes = _build_match_notes(best, ranked_candidates[1:] if len(ranked_candidates) > 1 else [])

    _save_match(
        db,
        activity=activity,
        planned_session=best["session"],
        training_day=training_day,
        confidence=confidence,
        method=method,
        notes=notes,
    )

    return ActivityMatchResult(
        activity_id=activity.id,
        matched=True,
        confidence=confidence,
        method=method,
        planned_session_id=best["session"].id,
        message=(
            f"Matched to planned session #{best['session'].id} with confidence {confidence:.2f}. "
            f"Debug: athlete_id={activity.athlete_id}, activity_date={activity_date.isoformat()}, "
            f"activity_sport={activity.sport_type!r}, session_sport={best['session'].sport_type!r}."
        ),
    )


def match_day_activities(db: Session, training_day_id: int) -> BatchMatchResult:
    training_day = _get_training_day_detail(db, training_day_id)
    if training_day is None:
        return BatchMatchResult(processed=0, matched=0, unmatched=0, messages=["Training day not found."])

    statement = (
        select(GarminActivity)
        .where(
            GarminActivity.athlete_id == training_day.athlete_id,
            GarminActivity.start_time.is_not(None),
        )
        .options(selectinload(GarminActivity.activity_match))
        .order_by(GarminActivity.start_time.asc(), GarminActivity.id.asc())
    )
    activities = [
        activity
        for activity in db.scalars(statement).all()
        if activity.start_time and activity.start_time.date() == training_day.day_date
    ]
    return _match_many(db, activities)


def match_recent_activities(db: Session, limit: int = 20) -> BatchMatchResult:
    statement = (
        select(GarminActivity)
        .options(selectinload(GarminActivity.activity_match))
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
        .limit(limit)
    )
    activities = list(db.scalars(statement).all())
    return _match_many(db, activities)


def _match_many(db: Session, activities: Iterable[GarminActivity]) -> BatchMatchResult:
    processed = 0
    matched = 0
    unmatched = 0
    messages: list[str] = []

    for activity in activities:
        result = match_activity_to_plan(db, activity.id)
        processed += 1
        if result.matched:
            matched += 1
        else:
            unmatched += 1
        messages.append(f"Activity {activity.id}: {result.message}")

    return BatchMatchResult(
        processed=processed,
        matched=matched,
        unmatched=unmatched,
        messages=messages,
    )


def _get_activity_with_context(db: Session, activity_id: int) -> GarminActivity | None:
    statement = (
        select(GarminActivity)
        .where(GarminActivity.id == activity_id)
        .options(
            selectinload(GarminActivity.activity_match),
            selectinload(GarminActivity.athlete),
        )
    )
    return db.scalar(statement)


def _get_training_day_for_activity(db: Session, activity: GarminActivity) -> TrainingDay | None:
    if activity.start_time is None or activity.athlete_id is None:
        return None
    statement = (
        select(TrainingDay)
        .where(
            TrainingDay.athlete_id == activity.athlete_id,
            TrainingDay.day_date == activity.start_time.date(),
        )
        .options(
            selectinload(TrainingDay.planned_sessions).selectinload(PlannedSession.session_group),
            selectinload(TrainingDay.planned_sessions).selectinload(PlannedSession.activity_match),
            selectinload(TrainingDay.session_groups),
        )
    )
    return db.scalar(statement)


def _get_training_day_detail(db: Session, training_day_id: int) -> TrainingDay | None:
    statement = (
        select(TrainingDay)
        .where(TrainingDay.id == training_day_id)
        .options(
            selectinload(TrainingDay.planned_sessions).selectinload(PlannedSession.session_group),
            selectinload(TrainingDay.planned_sessions).selectinload(PlannedSession.activity_match),
            selectinload(TrainingDay.session_groups),
        )
    )
    return db.scalar(statement)


def _ordered_sessions(sessions: Iterable[PlannedSession]) -> list[PlannedSession]:
    def sort_key(session: PlannedSession) -> tuple[int, int, int]:
        group_rank = session.session_group.group_order if session.session_group else 9999
        planned_minutes = (
            session.planned_start_time.hour * 60 + session.planned_start_time.minute
            if session.planned_start_time
            else 9999
        )
        return (planned_minutes, group_rank, session.session_order)

    return sorted(sessions, key=sort_key)


def _activity_rank_for_day(db: Session, activity: GarminActivity, training_day: TrainingDay) -> int | None:
    statement = (
        select(GarminActivity)
        .where(
            GarminActivity.athlete_id == training_day.athlete_id,
            GarminActivity.start_time.is_not(None),
        )
        .order_by(GarminActivity.start_time.asc(), GarminActivity.id.asc())
    )
    same_day_activities = [
        item
        for item in db.scalars(statement).all()
        if item.start_time and item.start_time.date() == training_day.day_date
    ]
    for index, item in enumerate(same_day_activities, start=1):
        if item.id == activity.id:
            return index
    return None


def _score_candidate(
    activity: GarminActivity,
    training_day: TrainingDay,
    session: PlannedSession,
    ordered_sessions: list[PlannedSession],
    activity_rank: int | None,
) -> dict[str, object]:
    score = 30.0
    exact_time = False
    if session.planned_start_time and activity.start_time:
        planned_dt = datetime.combine(training_day.day_date, session.planned_start_time)
        diff_minutes = abs((activity.start_time.replace(tzinfo=None) - planned_dt).total_seconds()) / 60.0
        if diff_minutes <= 30:
            score += 35
            exact_time = True
        elif diff_minutes <= 90:
            score += 22
        elif diff_minutes <= 180:
            score += 10
    else:
        diff_minutes = None
        score += 6

    if session.expected_duration_min and activity.duration_sec:
        actual_minutes = activity.duration_sec / 60.0
        duration_diff = abs(actual_minutes - session.expected_duration_min)
        if duration_diff <= 15:
            score += 18
        elif duration_diff <= 30:
            score += 10
        elif duration_diff <= 60:
            score += 4
    else:
        duration_diff = None
        score += 4

    session_rank = ordered_sessions.index(session) + 1
    if activity_rank is not None:
        rank_diff = abs(session_rank - activity_rank)
        if rank_diff == 0:
            score += 14
        elif rank_diff == 1:
            score += 8
        elif rank_diff == 2:
            score += 3
    else:
        rank_diff = None

    compatibility = _evaluate_sport_compatibility(activity, session)
    if compatibility["variant_bonus"]:
        score += 3

    if session.session_group is not None:
        score += 4

    return {
        "session": session,
        "score": min(score, 100.0),
        "exact_time": exact_time,
        "diff_minutes": diff_minutes,
        "duration_diff": duration_diff,
        "rank_diff": rank_diff,
        "has_group": session.session_group is not None,
    }


def _derive_match_method(candidate: dict[str, object]) -> str:
    if candidate["exact_time"]:
        return "exact_time"
    if candidate["has_group"]:
        return "group_match"
    return "same_day_sport"


def _build_match_notes(best: dict[str, object], alternatives: list[dict[str, object]]) -> str:
    notes = [
        f"score={best['score']:.1f}",
        f"time_diff_min={best['diff_minutes'] if best['diff_minutes'] is not None else 'n/a'}",
        f"duration_diff_min={best['duration_diff'] if best['duration_diff'] is not None else 'n/a'}",
        f"order_diff={best['rank_diff'] if best['rank_diff'] is not None else 'n/a'}",
    ]
    if alternatives:
        next_best = alternatives[0]
        notes.append(f"next_best_score={next_best['score']:.1f}")
    return " | ".join(notes)


def _save_match(
    db: Session,
    *,
    activity: GarminActivity,
    planned_session: PlannedSession,
    training_day: TrainingDay,
    confidence: float,
    method: str,
    notes: str,
) -> None:
    existing_activity_match = activity.activity_match
    existing_planned_match = planned_session.activity_match

    if existing_planned_match is not None and existing_planned_match is not existing_activity_match:
        db.delete(existing_planned_match)
        db.flush()

    if existing_activity_match is None:
        match = ActivitySessionMatch(
            athlete_id=activity.athlete_id,
            garmin_activity_id_fk=activity.id,
            planned_session_id_fk=planned_session.id,
            training_day_id_fk=training_day.id,
            match_confidence=confidence,
            match_method=method,
            match_notes=notes,
        )
        db.add(match)
    else:
        existing_activity_match.athlete_id = activity.athlete_id
        existing_activity_match.garmin_activity_id_fk = activity.id
        existing_activity_match.planned_session_id_fk = planned_session.id
        existing_activity_match.training_day_id_fk = training_day.id
        existing_activity_match.match_confidence = confidence
        existing_activity_match.match_method = method
        existing_activity_match.match_notes = notes
        db.add(existing_activity_match)

    db.commit()


def _delete_existing_activity_match(db: Session, activity: GarminActivity) -> None:
    if activity.activity_match is not None:
        db.delete(activity.activity_match)
        db.commit()


def _evaluate_sport_compatibility(activity: GarminActivity, session: PlannedSession) -> dict[str, object]:
    activity_sport = _normalize_sport(activity.sport_type)
    session_sport = _normalize_sport(session.sport_type)
    activity_variant = _normalize_variant(activity.discipline_variant)
    session_variant = _normalize_variant(session.discipline_variant)

    if activity_sport is None:
        return {"session": session, "compatible": False, "reason": "activity sport_type is missing", "variant_bonus": False}
    if session_sport is None:
        return {"session": session, "compatible": False, "reason": "planned session sport_type is missing", "variant_bonus": False}
    if activity_sport != session_sport:
        return {
            "session": session,
            "compatible": False,
            "reason": f"sport mismatch after normalization: activity={activity_sport}, session={session_sport}",
            "variant_bonus": False,
        }
    if activity_variant and session_variant and activity_variant == session_variant:
        return {"session": session, "compatible": True, "reason": "sport and discipline_variant match", "variant_bonus": True}
    if activity_variant and session_variant and activity_variant != session_variant:
        return {
            "session": session,
            "compatible": True,
            "reason": f"base sport matches; discipline_variant differs ({activity_variant} vs {session_variant})",
            "variant_bonus": False,
        }
    return {"session": session, "compatible": True, "reason": "base sport matches; variant not required", "variant_bonus": False}


def _normalize_sport(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "running": "run",
        "run": "run",
        "correr": "run",
        "carrera": "run",
        "trote": "run",
        "trail_running": "run",
        "trail_run": "run",
        "running_trail": "run",
        "treadmill_running": "run",
        "cycling": "bike",
        "ciclismo": "bike",
        "bicicleta": "bike",
        "bike": "bike",
        "bike_ride": "bike",
        "road_cycling": "bike",
        "road_biking": "bike",
        "indoor_cycling": "bike",
        "gravel_cycling": "bike",
        "mountain_biking": "bike",
        "mountain_bike": "bike",
        "mtb": "bike",
        "swimming": "swim",
        "swim": "swim",
        "natacion": "swim",
        "natación": "swim",
        "lap_swimming": "swim",
        "pool_swim": "swim",
        "pool_swimming": "swim",
        "open_water_swimming": "swim",
        "walking": "walk",
        "hiking": "walk",
    }
    return aliases.get(normalized, normalized)


def _normalize_variant(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "road_cycling": "road",
        "road_biking": "road",
        "road": "road",
        "mtb": "mtb",
        "mountain_bike": "mtb",
        "mountain_biking": "mtb",
        "trail_running": "trail",
        "trail_run": "trail",
        "lap_swimming": "pool",
        "pool_swim": "pool",
        "pool_swimming": "pool",
        "open_water_swimming": "open_water",
    }
    return aliases.get(normalized, normalized)
