from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay


logger = logging.getLogger(__name__)

AUTO_MATCH_MIN_SCORE = 70.0
CANDIDATE_MIN_SCORE = 55.0
AUTO_MATCH_MIN_MARGIN = 6.0
AMBIGUOUS_MARGIN = 6.0

SPORT_WEIGHT = 35.0
DATE_WEIGHT = 25.0
TIME_WEIGHT = 10.0
DURATION_WEIGHT = 12.0
DISTANCE_WEIGHT = 8.0
ELEVATION_WEIGHT = 4.0
TITLE_WEIGHT = 2.0
BLOCK_WEIGHT = 4.0
SPORT_MISMATCH_PENALTY = 20.0


SPORT_FAMILY_ALIASES: dict[str, str] = {
    "running": "run",
    "run": "run",
    "street_running": "run",
    "road_running": "run",
    "trail_running": "run",
    "trail_run": "run",
    "running_trail": "run",
    "treadmill_running": "run",
    "treadmill": "run",
    "walking": "walk",
    "hiking": "walk",
    "cycling": "bike",
    "bike": "bike",
    "bike_ride": "bike",
    "road_cycling": "bike",
    "road_biking": "bike",
    "gravel_cycling": "bike",
    "indoor_cycling": "bike",
    "indoor_bike": "bike",
    "mountain_biking": "bike",
    "mountain_bike": "bike",
    "mtb": "bike",
    "swimming": "swim",
    "swim": "swim",
    "lap_swimming": "swim",
    "pool_swim": "swim",
    "open_water_swim": "swim",
    "strength_training": "strength",
    "strength": "strength",
    "gym": "strength",
    "functional_strength_training": "strength",
    "multisport": "multisport",
    "multisport_block": "multisport",
    "brick": "multisport",
    "duathlon": "multisport",
    "triathlon": "multisport",
}


VARIANT_ALIASES: dict[str, str] = {
    "road_cycling": "road",
    "road_biking": "road",
    "road": "road",
    "indoor_cycling": "indoor",
    "indoor_bike": "indoor",
    "mountain_bike": "mtb",
    "mountain_biking": "mtb",
    "mtb": "mtb",
    "trail_running": "trail",
    "trail_run": "trail",
    "street_running": "road",
    "road_running": "road",
    "treadmill_running": "treadmill",
    "treadmill": "treadmill",
    "lap_swimming": "pool",
    "pool_swim": "pool",
    "open_water_swim": "open_water",
}


@dataclass
class MatchCandidate:
    planned_session_id: int
    training_day_id: int
    training_plan_id: int | None
    training_plan_name: str | None
    session_name: str
    session_date: str
    sport_type: str | None
    score: float
    confidence: float
    reasons: list[str]
    components: dict[str, float]
    date_diff_days: int | None
    compatible_sport: bool
    has_existing_match: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["score"] = round(self.score, 1)
        payload["confidence"] = round(self.confidence, 2)
        return payload


@dataclass
class MatchDecision:
    activity_id: int
    status: str
    matched_session_id: int | None
    score: float | None
    confidence: float | None
    explanations: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    candidate_sessions: list[MatchCandidate] = field(default_factory=list)
    match_method: str | None = None
    preserved_manual_match: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "status": self.status,
            "matched_session_id": self.matched_session_id,
            "score": round(self.score, 1) if self.score is not None else None,
            "confidence": round(self.confidence, 2) if self.confidence is not None else None,
            "explanations": self.explanations,
            "reasons": self.reasons,
            "candidate_sessions": [item.to_dict() for item in self.candidate_sessions],
            "match_method": self.match_method,
            "preserved_manual_match": self.preserved_manual_match,
        }


@dataclass
class BatchMatchDecision:
    processed: int
    matched: int
    candidate: int
    ambiguous: int
    unmatched: int
    decisions: list[MatchDecision]

    def to_dict(self) -> dict[str, Any]:
        return {
            "processed": self.processed,
            "matched": self.matched,
            "candidate": self.candidate,
            "ambiguous": self.ambiguous,
            "unmatched": self.unmatched,
            "decisions": [item.to_dict() for item in self.decisions],
        }


def compatible_sport(activity_sport: str | None, session_sport: str | None) -> bool:
    activity_family = _sport_family(activity_sport)
    session_family = _sport_family(session_sport)
    if not activity_family or not session_family:
        return False
    return (
        activity_family == session_family
        or activity_family == "multisport"
        or session_family == "multisport"
    )


def find_candidate_sessions_for_activity(
    db: Session,
    activity_id: int,
    *,
    days_window: int = 1,
    training_plan_id: int | None = None,
) -> list[MatchCandidate]:
    activity = _get_activity_with_context(db, activity_id)
    if activity is None:
        raise ValueError("Activity not found.")
    if activity.athlete_id is None:
        raise ValueError("La actividad no tiene atleta asociado.")
    if activity.start_time is None:
        raise ValueError("La actividad no tiene fecha/hora de inicio.")

    candidates = _get_candidate_sessions(db, activity, days_window=days_window, training_plan_id=training_plan_id)
    scored = [score_activity_session_match(activity, session) for session in candidates]
    scored.sort(key=lambda item: (-item.score, item.date_diff_days or 999, item.planned_session_id))
    return scored


def find_manual_sessions_for_activity(
    db: Session,
    activity_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    sport_type: str | None = None,
    only_unmatched: bool = False,
    training_plan_id: int | None = None,
    limit: int = 5,
) -> list[MatchCandidate]:
    activity = _get_activity_with_context(db, activity_id)
    if activity is None:
        raise ValueError("Activity not found.")
    if activity.athlete_id is None:
        raise ValueError("La actividad no tiene atleta asociado.")
    if activity.start_time is None:
        raise ValueError("La actividad no tiene fecha/hora de inicio.")

    activity_date = _activity_local_date(activity)
    if date_from is None or date_to is None:
        if activity_date is None:
            raise ValueError("La actividad no tiene fecha/hora de inicio.")
        date_from = date_from or (activity_date - timedelta(days=1))
        date_to = date_to or (activity_date + timedelta(days=1))

    statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .where(
            PlannedSession.athlete_id == activity.athlete_id,
            TrainingDay.day_date >= date_from,
            TrainingDay.day_date <= date_to,
        )
        .options(
            selectinload(PlannedSession.training_day).selectinload(TrainingDay.training_plan),
            selectinload(PlannedSession.activity_match).selectinload(ActivitySessionMatch.garmin_activity),
            selectinload(PlannedSession.planned_session_steps),
            selectinload(PlannedSession.session_group),
        )
    )
    if sport_type:
        statement = statement.where(PlannedSession.sport_type == sport_type)

    sessions = list(db.scalars(statement).all())
    filtered: list[PlannedSession] = []
    for session in sessions:
        if only_unmatched and session.activity_match is not None:
            continue
        if session.activity_match and session.activity_match.garmin_activity_id_fk != activity.id:
            if session.activity_match.match_method == "manual":
                continue
        filtered.append(session)

    scored = [score_activity_session_match(activity, session) for session in filtered]
    scored.sort(
        key=lambda item: (
            0 if training_plan_id is not None and item.training_plan_id == training_plan_id else 1,
            -item.score,
            item.has_existing_match,
            item.date_diff_days or 999,
            item.planned_session_id,
        )
    )
    return scored[:limit]


def score_activity_session_match(activity: GarminActivity, planned_session: PlannedSession) -> MatchCandidate:
    reasons: list[str] = []
    components: dict[str, float] = {}
    activity_date = _activity_local_date(activity)
    session_date = planned_session.training_day.day_date if planned_session.training_day else None
    date_diff_days = abs((session_date - activity_date).days) if activity_date and session_date else None

    activity_sport = _normalize_sport(activity.sport_type)
    session_sport = _normalize_sport(planned_session.sport_type)
    exact_sport = activity_sport is not None and activity_sport == session_sport
    family_match = compatible_sport(activity.sport_type, planned_session.sport_type)
    variant_bonus = _normalize_variant(activity.discipline_variant) == _normalize_variant(planned_session.discipline_variant)
    sport_score = 0.0
    if exact_sport:
        sport_score = SPORT_WEIGHT
        reasons.append("mismo deporte")
    elif family_match:
        sport_score = SPORT_WEIGHT - 9.0
        reasons.append("misma familia deportiva")
    else:
        reasons.append("deporte incompatible")
    if variant_bonus and family_match:
        sport_score = min(SPORT_WEIGHT, sport_score + 4.0)
        reasons.append("variante compatible")
    components["sport"] = round(sport_score, 1)

    date_score = 0.0
    if date_diff_days == 0:
        date_score = DATE_WEIGHT
        reasons.append("mismo dia")
    elif date_diff_days == 1:
        date_score = 10.0
        reasons.append("fecha cercana")
    components["date"] = round(date_score, 1)

    time_score = 0.0
    if date_diff_days == 0 and planned_session.planned_start_time and activity.start_time:
        planned_dt = datetime.combine(session_date, planned_session.planned_start_time)
        actual_dt = activity.start_time.replace(tzinfo=None) if activity.start_time.tzinfo else activity.start_time
        diff_minutes = abs((actual_dt - planned_dt).total_seconds()) / 60.0
        if diff_minutes <= 30:
            time_score = TIME_WEIGHT
            reasons.append("horario muy cercano")
        elif diff_minutes <= 90:
            time_score = 6.0
            reasons.append("horario compatible")
        elif diff_minutes <= 180:
            time_score = 3.0
            reasons.append("horario razonable")
    components["time"] = round(time_score, 1)

    duration_score = _relative_component_score(
        expected=planned_session.expected_duration_min,
        actual=(activity.duration_sec / 60.0) if activity.duration_sec is not None else None,
        weight=DURATION_WEIGHT,
        reasons=reasons,
        label="duracion",
    )
    components["duration"] = round(duration_score, 1)

    distance_score = _relative_component_score(
        expected=planned_session.expected_distance_km,
        actual=(activity.distance_m / 1000.0) if activity.distance_m is not None else None,
        weight=DISTANCE_WEIGHT,
        reasons=reasons,
        label="distancia",
    )
    components["distance"] = round(distance_score, 1)

    elevation_score = _relative_component_score(
        expected=planned_session.expected_elevation_gain_m,
        actual=activity.elevation_gain_m,
        weight=ELEVATION_WEIGHT,
        reasons=reasons,
        label="desnivel",
    )
    components["elevation"] = round(elevation_score, 1)

    title_score = _title_component_score(activity, planned_session, reasons)
    components["title"] = round(title_score, 1)

    block_score = _block_component_score(activity, planned_session, reasons)
    components["blocks"] = round(block_score, 1)

    total_score = sum(components.values())
    if not family_match:
        total_score -= SPORT_MISMATCH_PENALTY
    total_score = max(0.0, min(100.0, round(total_score, 1)))
    confidence = round(total_score / 100.0, 2)

    return MatchCandidate(
        planned_session_id=planned_session.id,
        training_day_id=planned_session.training_day_id,
        training_plan_id=planned_session.training_day.training_plan_id if planned_session.training_day else None,
        training_plan_name=planned_session.training_day.training_plan.name if planned_session.training_day and planned_session.training_day.training_plan else None,
        session_name=planned_session.name,
        session_date=session_date.isoformat() if session_date else "-",
        sport_type=planned_session.sport_type,
        score=total_score,
        confidence=confidence,
        reasons=reasons,
        components=components,
        date_diff_days=date_diff_days,
        compatible_sport=family_match,
        has_existing_match=planned_session.activity_match is not None and planned_session.activity_match.garmin_activity_id_fk != activity.id,
    )


def auto_match_activity(
    db: Session,
    activity_id: int,
    *,
    preserve_manual: bool = True,
    training_plan_id: int | None = None,
) -> MatchDecision:
    activity = _get_activity_with_context(db, activity_id)
    if activity is None:
        raise ValueError("Activity not found.")
    if activity.athlete_id is None:
        return MatchDecision(activity_id=activity_id, status="unmatched", matched_session_id=None, score=None, confidence=None, explanations=["La actividad no tiene atleta asociado."])
    if activity.start_time is None:
        _delete_existing_auto_match(db, activity)
        return MatchDecision(activity_id=activity_id, status="unmatched", matched_session_id=None, score=None, confidence=None, explanations=["La actividad no tiene fecha/hora de inicio."])

    if preserve_manual and activity.activity_match and activity.activity_match.match_method == "manual":
        current = activity.activity_match
        return MatchDecision(
            activity_id=activity.id,
            status="matched",
            matched_session_id=current.planned_session_id_fk,
            score=(current.match_confidence or 0.0) * 100.0 if current.match_confidence is not None else None,
            confidence=current.match_confidence,
            explanations=["Se preservo la vinculacion manual existente."],
            reasons=[current.match_notes or "Match manual vigente."],
            candidate_sessions=[],
            match_method="manual",
            preserved_manual_match=True,
        )

    candidates = find_candidate_sessions_for_activity(db, activity.id, training_plan_id=training_plan_id)
    decision = _decide_match(activity.id, candidates)

    if decision.status == "matched" and decision.matched_session_id is not None:
        planned_session = db.get(PlannedSession, decision.matched_session_id)
        training_day = planned_session.training_day if planned_session else None
        if planned_session is None or training_day is None:
            raise ValueError("No se pudo cargar la sesion elegida para guardar el match.")
        _persist_match(
            db,
            activity=activity,
            planned_session=planned_session,
            training_day=training_day,
            confidence=decision.confidence or 0.0,
            method=decision.match_method or "same_day_candidate",
            explanation=_build_match_explanation(decision),
        )
    else:
        _delete_existing_auto_match(db, activity)

    return decision


def auto_match_unlinked_activities(
    db: Session,
    athlete_id: int | None = None,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    only_unmatched: bool = True,
    training_plan_id: int | None = None,
) -> BatchMatchDecision:
    statement = (
        select(GarminActivity)
        .options(selectinload(GarminActivity.activity_match))
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
    )
    if athlete_id is not None:
        statement = statement.where(GarminActivity.athlete_id == athlete_id)

    activities = list(db.scalars(statement).all())
    filtered: list[GarminActivity] = []
    for activity in activities:
        activity_date = _activity_local_date(activity)
        if date_from and (activity_date is None or activity_date < date_from):
            continue
        if date_to and (activity_date is None or activity_date > date_to):
            continue
        if only_unmatched and activity.activity_match is not None:
            continue
        filtered.append(activity)

    decisions: list[MatchDecision] = []
    for activity in filtered:
        decisions.append(auto_match_activity(db, activity.id, training_plan_id=training_plan_id))

    return BatchMatchDecision(
        processed=len(decisions),
        matched=sum(1 for item in decisions if item.status == "matched"),
        candidate=sum(1 for item in decisions if item.status == "candidate"),
        ambiguous=sum(1 for item in decisions if item.status == "ambiguous"),
        unmatched=sum(1 for item in decisions if item.status == "unmatched"),
        decisions=decisions,
    )


def manual_match_activity(
    db: Session,
    activity_id: int,
    planned_session_id: int,
) -> MatchDecision:
    activity = _get_activity_with_context(db, activity_id)
    if activity is None:
        raise ValueError("Activity not found.")
    if activity.activity_match and activity.activity_match.planned_session_id_fk == planned_session_id:
        return MatchDecision(
            activity_id=activity.id,
            status="matched",
            matched_session_id=planned_session_id,
            score=None,
            confidence=activity.activity_match.match_confidence,
            explanations=["La actividad ya estaba vinculada con esta sesion."],
            reasons=[activity.activity_match.match_notes or "Vinculacion existente."],
            candidate_sessions=[],
            match_method=activity.activity_match.match_method,
        )
    if (
        activity.activity_match
        and activity.activity_match.planned_session_id_fk != planned_session_id
        and activity.activity_match.match_method == "manual"
    ):
        raise ValueError("La actividad ya esta vinculada a otra sesion. Desvinculala antes de cambiar.")
    planned_session = _get_planned_session_with_context(db, planned_session_id)
    if planned_session is None:
        raise ValueError("Planned session not found.")
    if activity.athlete_id != planned_session.athlete_id:
        raise ValueError("La actividad y la sesion no pertenecen al mismo atleta.")
    if planned_session.training_day is None:
        raise ValueError("La sesion no tiene training day asociado.")
    if planned_session.activity_match and planned_session.activity_match.garmin_activity_id_fk != activity.id:
        raise ValueError("La sesion elegida ya tiene otra actividad vinculada.")

    candidate = score_activity_session_match(activity, planned_session)
    _persist_match(
        db,
        activity=activity,
        planned_session=planned_session,
        training_day=planned_session.training_day,
        confidence=candidate.confidence,
        method="manual",
        explanation=(
            "Match manual confirmado. "
            f"Score de referencia: {candidate.score:.1f}. "
            f"Motivos: {', '.join(candidate.reasons[:4])}."
        ),
    )
    return MatchDecision(
        activity_id=activity.id,
        status="matched",
        matched_session_id=planned_session.id,
        score=candidate.score,
        confidence=candidate.confidence,
        explanations=["La actividad se vinculo manualmente."],
        reasons=candidate.reasons,
        candidate_sessions=[candidate],
        match_method="manual",
    )


def preview_activity_match(db: Session, activity_id: int, *, training_plan_id: int | None = None) -> MatchDecision:
    activity = _get_activity_with_context(db, activity_id)
    if activity is None:
        raise ValueError("Activity not found.")
    if activity.activity_match is not None:
        current_candidate = score_activity_session_match(activity, activity.activity_match.planned_session) if activity.activity_match.planned_session else None
        return MatchDecision(
            activity_id=activity.id,
            status="matched",
            matched_session_id=activity.activity_match.planned_session_id_fk,
            score=current_candidate.score if current_candidate else ((activity.activity_match.match_confidence or 0) * 100.0),
            confidence=current_candidate.confidence if current_candidate else activity.activity_match.match_confidence,
            explanations=["La actividad ya tiene una sesion vinculada."],
            reasons=[activity.activity_match.match_notes or "Vinculacion existente."],
            candidate_sessions=[current_candidate] if current_candidate else [],
            match_method=activity.activity_match.match_method,
        )
    candidates = find_candidate_sessions_for_activity(db, activity.id, training_plan_id=training_plan_id)
    return _decide_match(activity.id, candidates)


def _decide_match(activity_id: int, candidates: list[MatchCandidate]) -> MatchDecision:
    if not candidates:
        return MatchDecision(
            activity_id=activity_id,
            status="unmatched",
            matched_session_id=None,
            score=None,
            confidence=None,
            explanations=["No se encontraron sesiones candidatas para esta actividad."],
            reasons=[],
            candidate_sessions=[],
        )

    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    margin = (top.score - second.score) if second else None
    explanations = [
        f"Mejor candidata: sesion #{top.planned_session_id} con score {top.score:.1f}.",
    ]
    if second is not None:
        explanations.append(
            f"Segunda candidata: sesion #{second.planned_session_id} con score {second.score:.1f}."
        )

    if (
        top.compatible_sport
        and top.date_diff_days == 0
        and top.score >= AUTO_MATCH_MIN_SCORE
        and (margin is None or margin >= AUTO_MATCH_MIN_MARGIN)
    ):
        return MatchDecision(
            activity_id=activity_id,
            status="matched",
            matched_session_id=top.planned_session_id,
            score=top.score,
            confidence=top.confidence,
            explanations=explanations + ["El score es alto y no hay ambigüedad relevante."],
            reasons=top.reasons,
            candidate_sessions=candidates[:5],
            match_method=_derive_auto_match_method(top),
        )

    if top.score >= CANDIDATE_MIN_SCORE and second is not None and (margin is None or margin < AMBIGUOUS_MARGIN):
        return MatchDecision(
            activity_id=activity_id,
            status="ambiguous",
            matched_session_id=None,
            score=top.score,
            confidence=top.confidence,
            explanations=explanations + ["Hay mas de una sesion fuerte y la diferencia entre candidatas es baja."],
            reasons=top.reasons,
            candidate_sessions=candidates[:5],
            match_method=None,
        )

    if top.score >= CANDIDATE_MIN_SCORE and top.compatible_sport:
        return MatchDecision(
            activity_id=activity_id,
            status="candidate",
            matched_session_id=None,
            score=top.score,
            confidence=top.confidence,
            explanations=explanations + ["Hay una candidata razonable, pero no alcanza para auto-vincular con seguridad."],
            reasons=top.reasons,
            candidate_sessions=candidates[:5],
            match_method=None,
        )

    return MatchDecision(
        activity_id=activity_id,
        status="unmatched",
        matched_session_id=None,
        score=top.score,
        confidence=top.confidence,
        explanations=explanations + ["Ninguna candidata alcanzo el umbral minimo para vincular."],
        reasons=top.reasons,
        candidate_sessions=candidates[:5],
        match_method=None,
    )


def _relative_component_score(
    *,
    expected: float | None,
    actual: float | None,
    weight: float,
    reasons: list[str],
    label: str,
) -> float:
    if expected in (None, 0) or actual is None:
        return 0.0
    delta_pct = abs(actual - expected) / expected * 100.0
    if delta_pct <= 10:
        reasons.append(f"{label} muy cercana")
        return weight
    if delta_pct <= 20:
        reasons.append(f"{label} compatible")
        return weight * 0.75
    if delta_pct <= 35:
        reasons.append(f"{label} razonable")
        return weight * 0.4
    return 0.0


def _title_component_score(activity: GarminActivity, planned_session: PlannedSession, reasons: list[str]) -> float:
    activity_text = _normalized_tokens(activity.activity_name)
    session_text = _normalized_tokens(" ".join(filter(None, [planned_session.name, planned_session.description_text, planned_session.target_notes])))
    if not activity_text or not session_text:
        return 0.0
    overlap = activity_text.intersection(session_text)
    if len(overlap) >= 2:
        reasons.append("titulo con palabras en comun")
        return TITLE_WEIGHT
    if len(overlap) == 1:
        return TITLE_WEIGHT * 0.5
    return 0.0


def _block_component_score(activity: GarminActivity, planned_session: PlannedSession, reasons: list[str]) -> float:
    planned_steps = list(planned_session.planned_session_steps or [])
    laps = list(activity.laps or [])
    if not planned_steps or not laps:
        return 0.0
    coverage = min(len(planned_steps), len(laps)) / max(len(planned_steps), len(laps))
    if coverage >= 0.9:
        reasons.append("estructura de bloques/laps muy parecida")
        return BLOCK_WEIGHT
    if coverage >= 0.6:
        reasons.append("estructura parcialmente compatible")
        return BLOCK_WEIGHT * 0.5
    return 0.0


def _derive_auto_match_method(candidate: MatchCandidate) -> str:
    reasons = set(candidate.reasons)
    if "horario muy cercano" in reasons:
        return "exact_time"
    if "mismo deporte" in reasons:
        return "same_day_sport"
    if "misma familia deportiva" in reasons:
        return "same_day_family"
    return "same_day_candidate"


def _build_match_explanation(decision: MatchDecision) -> str:
    base = " ".join(decision.explanations)
    reasons = ", ".join(decision.reasons[:5])
    if reasons:
        return f"{base} Motivos principales: {reasons}."
    return base


def _persist_match(
    db: Session,
    *,
    activity: GarminActivity,
    planned_session: PlannedSession,
    training_day: TrainingDay,
    confidence: float,
    method: str,
    explanation: str,
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
            match_notes=explanation,
        )
        db.add(match)
    else:
        existing_activity_match.athlete_id = activity.athlete_id
        existing_activity_match.garmin_activity_id_fk = activity.id
        existing_activity_match.planned_session_id_fk = planned_session.id
        existing_activity_match.training_day_id_fk = training_day.id
        existing_activity_match.match_confidence = confidence
        existing_activity_match.match_method = method
        existing_activity_match.match_notes = explanation
        db.add(existing_activity_match)

    db.commit()


def _delete_existing_auto_match(db: Session, activity: GarminActivity) -> None:
    if activity.activity_match is None:
        return
    if activity.activity_match.match_method == "manual":
        return
    db.delete(activity.activity_match)
    db.commit()


def _get_candidate_sessions(db: Session, activity: GarminActivity, *, days_window: int, training_plan_id: int | None = None) -> list[PlannedSession]:
    activity_date = _activity_local_date(activity)
    if activity_date is None:
        return []

    statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .where(
            PlannedSession.athlete_id == activity.athlete_id,
            TrainingDay.day_date >= activity_date - timedelta(days=days_window),
            TrainingDay.day_date <= activity_date + timedelta(days=days_window),
        )
        .options(
            selectinload(PlannedSession.training_day).selectinload(TrainingDay.training_plan),
            selectinload(PlannedSession.activity_match).selectinload(ActivitySessionMatch.garmin_activity),
            selectinload(PlannedSession.planned_session_steps),
            selectinload(PlannedSession.session_group),
        )
    )
    if training_plan_id is not None:
        statement = statement.where(TrainingDay.training_plan_id == training_plan_id)
    sessions = list(db.scalars(statement).all())
    filtered: list[PlannedSession] = []
    for session in sessions:
        if session.activity_match and session.activity_match.garmin_activity_id_fk != activity.id:
            if session.activity_match.match_method == "manual":
                continue
        filtered.append(session)
    return filtered


def _get_activity_with_context(db: Session, activity_id: int) -> GarminActivity | None:
    statement = (
        select(GarminActivity)
        .where(GarminActivity.id == activity_id)
        .options(
            selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session).selectinload(PlannedSession.training_day),
            selectinload(GarminActivity.laps),
            selectinload(GarminActivity.athlete),
        )
    )
    return db.scalar(statement)


def _get_planned_session_with_context(db: Session, planned_session_id: int) -> PlannedSession | None:
    statement = (
        select(PlannedSession)
        .where(PlannedSession.id == planned_session_id)
        .options(
            selectinload(PlannedSession.training_day).selectinload(TrainingDay.training_plan),
            selectinload(PlannedSession.activity_match),
            selectinload(PlannedSession.planned_session_steps),
            selectinload(PlannedSession.session_group),
        )
    )
    return db.scalar(statement)


def _activity_local_date(activity: GarminActivity) -> date | None:
    if activity.start_time is None:
        return None
    if activity.start_time.tzinfo is not None:
        return activity.start_time.astimezone().date()
    return activity.start_time.date()


def _normalize_sport(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "running": "run",
        "run": "run",
        "street_running": "run",
        "road_running": "run",
        "trail_running": "run",
        "trail_run": "run",
        "running_trail": "run",
        "treadmill_running": "run",
        "treadmill": "run",
        "cycling": "bike",
        "bike": "bike",
        "road_cycling": "bike",
        "road_biking": "bike",
        "gravel_cycling": "bike",
        "indoor_cycling": "bike",
        "indoor_bike": "bike",
        "mountain_bike": "bike",
        "mountain_biking": "bike",
        "mtb": "bike",
        "swimming": "swim",
        "swim": "swim",
        "lap_swimming": "swim",
        "pool_swim": "swim",
        "open_water_swim": "swim",
        "strength_training": "strength",
        "strength": "strength",
        "gym": "strength",
        "correr": "run",
        "carrera": "run",
        "natacion": "swim",
        "bicicleta": "bike",
    }
    return aliases.get(normalized, normalized)


def _sport_family(value: str | None) -> str | None:
    normalized = _normalize_sport(value)
    if not normalized:
        return None
    return SPORT_FAMILY_ALIASES.get(normalized, normalized)


def _normalize_variant(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return VARIANT_ALIASES.get(normalized, normalized)


def _normalized_tokens(value: str | None) -> set[str]:
    if not value:
        return set()
    tokens = []
    for raw_token in value.lower().replace("-", " ").replace("_", " ").split():
        token = raw_token.strip(".,;:()[]{}!?")
        if len(token) >= 3:
            tokens.append(token)
    return set(tokens)
