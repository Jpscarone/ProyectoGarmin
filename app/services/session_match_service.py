from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.services.modality import normalize_modality, preferred_modality
from app.services.garmin.profile_sync import load_zone_payload
from app.services.planning.presentation import (
    SessionDisplayBlock,
    SessionDisplayRepeatBlock,
    SessionDisplaySimpleStep,
    build_session_display_blocks_for_session,
    derive_session_metrics,
)
from app.utils.datetime_utils import to_local_date, to_local_datetime


logger = logging.getLogger(__name__)

AUTO_MATCH_DIRECT_SCORE = 80.0
AUTO_MATCH_REVIEW_SCORE = 65.0
RECOMMENDED_CANDIDATE_SCORE = 50.0
AUTO_MATCH_MIN_MARGIN = 15.0
AMBIGUOUS_MIN_SCORE = 60.0
AMBIGUOUS_MARGIN = 15.0

SCORE_WEIGHTS: dict[str, dict[str, float]] = {
    "time_based": {
        "date": 30.0,
        "sport": 25.0,
        "duration": 25.0,
        "intensity": 15.0,
        "distance": 5.0,
        "structure": 0.0,
    },
    "distance_based": {
        "date": 30.0,
        "sport": 25.0,
        "distance": 25.0,
        "duration": 15.0,
        "intensity": 5.0,
        "structure": 0.0,
    },
    "structured": {
        "date": 25.0,
        "sport": 20.0,
        "duration": 15.0,
        "structure": 25.0,
        "intensity": 15.0,
        "distance": 0.0,
    },
}

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
    confidence_level: str
    match_reasons: list[str]
    match_penalties: list[str]
    components: dict[str, float]
    date_diff_days: int | None
    compatible_sport: bool
    hard_compatible: bool
    has_existing_match: bool
    session_kind: str
    auto_link_allowed: bool
    auto_link_decision_reason: str

    @property
    def reasons(self) -> list[str]:
        return self.match_reasons

    @property
    def penalties(self) -> list[str]:
        return self.match_penalties

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["score"] = round(self.score, 1)
        payload["confidence"] = round(self.confidence, 2)
        payload["reasons"] = list(self.match_reasons)
        payload["penalties"] = list(self.match_penalties)
        return payload


@dataclass
class MatchDecision:
    activity_id: int
    status: str
    matched_session_id: int | None
    score: float | None
    confidence: float | None
    confidence_level: str | None = None
    explanations: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    candidate_sessions: list[MatchCandidate] = field(default_factory=list)
    match_method: str | None = None
    preserved_manual_match: bool = False
    auto_link_allowed: bool = False
    auto_link_decision_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "status": self.status,
            "matched_session_id": self.matched_session_id,
            "score": round(self.score, 1) if self.score is not None else None,
            "confidence": round(self.confidence, 2) if self.confidence is not None else None,
            "confidence_level": self.confidence_level,
            "explanations": self.explanations,
            "reasons": self.reasons,
            "penalties": self.penalties,
            "match_reasons": self.reasons,
            "match_penalties": self.penalties,
            "candidate_sessions": [item.to_dict() for item in self.candidate_sessions],
            "match_method": self.match_method,
            "preserved_manual_match": self.preserved_manual_match,
            "auto_link_allowed": self.auto_link_allowed,
            "auto_link_decision_reason": self.auto_link_decision_reason,
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
            selectinload(PlannedSession.athlete),
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
    match_reasons: list[str] = []
    match_penalties: list[str] = []
    components: dict[str, float] = {}

    activity_date = _activity_local_date(activity)
    session_date = planned_session.training_day.day_date if planned_session.training_day else None
    date_diff_days = abs((session_date - activity_date).days) if activity_date and session_date else None

    same_athlete = activity.athlete_id == planned_session.athlete_id
    family_match = compatible_sport(activity.sport_type, planned_session.sport_type)
    metrics = derive_session_metrics(planned_session)
    expected_duration_min = (metrics.duration_sec / 60.0) if metrics.duration_sec is not None else planned_session.expected_duration_min
    expected_distance_km = (metrics.distance_m / 1000.0) if metrics.distance_m is not None else planned_session.expected_distance_km
    session_kind = _detect_session_kind(planned_session, expected_duration_min, expected_distance_km)
    modality_profile = _match_modality_profile(activity, planned_session)
    weights = _score_weights_for_profile(session_kind, modality_profile)

    if not same_athlete:
        match_penalties.append("la sesion pertenece a otro atleta")
    if not family_match:
        match_penalties.append("deporte incompatible")
    if date_diff_days is None:
        match_penalties.append("no se pudo comparar la fecha local")
    elif date_diff_days > 1:
        match_penalties.append(f"fecha fuera de rango ({date_diff_days} dias)")

    components["date"] = round(
        _date_component_score(date_diff_days, weights["date"], match_reasons, match_penalties),
        1,
    )
    components["sport"] = round(
        _sport_component_score(activity, planned_session, weights["sport"], match_reasons, match_penalties),
        1,
    )
    components["duration"] = round(
        _duration_component_score(
            expected_duration_min,
            (activity.duration_sec / 60.0) if activity.duration_sec is not None else None,
            weights["duration"],
            match_reasons,
            match_penalties,
        ),
        1,
    )
    components["distance"] = round(
        _distance_component_score(
            session_kind=session_kind,
            expected_distance_km=expected_distance_km,
            actual_distance_km=(activity.distance_m / 1000.0) if activity.distance_m is not None else None,
            weight=weights["distance"],
            modality_profile=modality_profile,
            match_reasons=match_reasons,
            match_penalties=match_penalties,
        ),
        1,
    )
    components["structure"] = round(
        _structure_component_score(
            activity,
            planned_session,
            weight=weights["structure"],
            match_reasons=match_reasons,
            match_penalties=match_penalties,
        ),
        1,
    )
    components["intensity"] = round(
        _intensity_component_score(
            activity,
            planned_session,
            weight=weights["intensity"],
            match_reasons=match_reasons,
            match_penalties=match_penalties,
        ),
        1,
    )

    total_score = sum(components.values())
    if modality_profile["explicit_mismatch"]:
        total_score -= 10.0
        _append_unique(match_penalties, "modalidad distinta entre plan y actividad")
    elif modality_profile["explicit_match"]:
        _append_unique(match_reasons, f"modalidad {modality_profile['effective_modality']} consistente")
    if not same_athlete or not family_match or (date_diff_days is not None and date_diff_days > 1):
        total_score = min(total_score, 49.0)
    total_score = max(0.0, min(100.0, round(total_score, 1)))
    confidence = round(total_score / 100.0, 2)
    confidence_level = _confidence_level_for_score(total_score)
    hard_compatible = bool(same_athlete and family_match and date_diff_days is not None and date_diff_days <= 1)

    candidate = MatchCandidate(
        planned_session_id=planned_session.id,
        training_day_id=planned_session.training_day_id,
        training_plan_id=planned_session.training_day.training_plan_id if planned_session.training_day else None,
        training_plan_name=planned_session.training_day.training_plan.name if planned_session.training_day and planned_session.training_day.training_plan else None,
        session_name=planned_session.name,
        session_date=session_date.isoformat() if session_date else "-",
        sport_type=planned_session.sport_type,
        score=total_score,
        confidence=confidence,
        confidence_level=confidence_level,
        match_reasons=match_reasons,
        match_penalties=match_penalties,
        components=components,
        date_diff_days=date_diff_days,
        compatible_sport=family_match,
        hard_compatible=hard_compatible,
        has_existing_match=planned_session.activity_match is not None and planned_session.activity_match.garmin_activity_id_fk != activity.id,
        session_kind=session_kind,
        auto_link_allowed=False,
        auto_link_decision_reason=_candidate_default_decision_reason(total_score, hard_compatible),
    )
    return candidate


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
        return MatchDecision(
            activity_id=activity_id,
            status="unmatched",
            matched_session_id=None,
            score=None,
            confidence=None,
            explanations=["La actividad no tiene atleta asociado."],
            auto_link_decision_reason="No se pudo evaluar el match porque falta el atleta de la actividad.",
        )
    if activity.start_time is None:
        _delete_existing_auto_match(db, activity)
        return MatchDecision(
            activity_id=activity_id,
            status="unmatched",
            matched_session_id=None,
            score=None,
            confidence=None,
            explanations=["La actividad no tiene fecha/hora de inicio."],
            auto_link_decision_reason="No se pudo evaluar el match porque falta la fecha de la actividad.",
        )

    if preserve_manual and activity.activity_match and activity.activity_match.match_method == "manual":
        current = activity.activity_match
        return MatchDecision(
            activity_id=activity.id,
            status="matched",
            matched_session_id=current.planned_session_id_fk,
            score=(current.match_confidence or 0.0) * 100.0 if current.match_confidence is not None else None,
            confidence=current.match_confidence,
            confidence_level=_confidence_level_for_score((current.match_confidence or 0.0) * 100.0),
            explanations=["Se preservo la vinculacion manual existente."],
            reasons=[current.match_notes or "Match manual vigente."],
            penalties=[],
            candidate_sessions=[],
            match_method="manual",
            preserved_manual_match=True,
            auto_link_allowed=False,
            auto_link_decision_reason="La actividad ya tenia una vinculacion manual confirmada.",
        )

    if activity.activity_match and activity.activity_match.planned_session is not None:
        current_candidate = score_activity_session_match(activity, activity.activity_match.planned_session)
        return MatchDecision(
            activity_id=activity.id,
            status="matched",
            matched_session_id=activity.activity_match.planned_session_id_fk,
            score=current_candidate.score,
            confidence=current_candidate.confidence,
            confidence_level=current_candidate.confidence_level,
            explanations=["La actividad ya tiene una sesion vinculada y no se reevaluo automaticamente."],
            reasons=current_candidate.match_reasons,
            penalties=current_candidate.match_penalties,
            candidate_sessions=[current_candidate],
            match_method=activity.activity_match.match_method,
            auto_link_allowed=False,
            auto_link_decision_reason="La actividad ya estaba vinculada previamente.",
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
            confidence_level=_confidence_level_for_score((activity.activity_match.match_confidence or 0.0) * 100.0),
            explanations=["La actividad ya estaba vinculada con esta sesion."],
            reasons=[activity.activity_match.match_notes or "Vinculacion existente."],
            penalties=[],
            candidate_sessions=[],
            match_method=activity.activity_match.match_method,
            auto_link_allowed=False,
            auto_link_decision_reason="La actividad ya estaba vinculada con esta sesion.",
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
            f"Motivos: {', '.join(candidate.match_reasons[:4])}."
        ),
    )
    return MatchDecision(
        activity_id=activity.id,
        status="matched",
        matched_session_id=planned_session.id,
        score=candidate.score,
        confidence=candidate.confidence,
        confidence_level=candidate.confidence_level,
        explanations=["La actividad se vinculo manualmente."],
        reasons=candidate.match_reasons,
        penalties=candidate.match_penalties,
        candidate_sessions=[candidate],
        match_method="manual",
        auto_link_allowed=True,
        auto_link_decision_reason="La vinculacion fue confirmada manualmente por el usuario.",
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
            confidence_level=current_candidate.confidence_level if current_candidate else _confidence_level_for_score((activity.activity_match.match_confidence or 0) * 100.0),
            explanations=["La actividad ya tiene una sesion vinculada."],
            reasons=current_candidate.match_reasons if current_candidate else [activity.activity_match.match_notes or "Vinculacion existente."],
            penalties=current_candidate.match_penalties if current_candidate else [],
            candidate_sessions=[current_candidate] if current_candidate else [],
            match_method=activity.activity_match.match_method,
            auto_link_allowed=False,
            auto_link_decision_reason="La actividad ya esta vinculada.",
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
            confidence_level=None,
            explanations=["No se encontraron sesiones candidatas para esta actividad."],
            reasons=[],
            penalties=[],
            candidate_sessions=[],
            auto_link_allowed=False,
            auto_link_decision_reason="No se encontraron sesiones del mismo atleta, deporte y fecha compatibles.",
        )

    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    margin = (top.score - second.score) if second else None
    reasonable_same_day = [
        candidate
        for candidate in candidates
        if candidate.hard_compatible and candidate.date_diff_days == 0 and candidate.score >= AUTO_MATCH_REVIEW_SCORE
    ]
    ambiguous_pair = bool(
        second is not None
        and top.score >= AMBIGUOUS_MIN_SCORE
        and second.score >= AMBIGUOUS_MIN_SCORE
        and (top.score - second.score) < AMBIGUOUS_MARGIN
    )

    explanations = [f"Mejor candidata: sesion #{top.planned_session_id} con score {top.score:.1f}."]
    if second is not None:
        explanations.append(f"Segunda candidata: sesion #{second.planned_session_id} con score {second.score:.1f}.")

    _decorate_candidates_for_decision(candidates, top, second)

    if ambiguous_pair:
        _append_unique(candidates[0].match_penalties, "hay otro candidato similar")
        if second is not None:
            _append_unique(second.match_penalties, "hay otro candidato similar")
        return MatchDecision(
            activity_id=activity_id,
            status="ambiguous",
            matched_session_id=None,
            score=top.score,
            confidence=top.confidence,
            confidence_level=top.confidence_level,
            explanations=explanations + ["Hay varias candidatas fuertes y la diferencia entre ellas es menor a 15 puntos."],
            reasons=top.match_reasons,
            penalties=top.match_penalties,
            candidate_sessions=candidates[:5],
            auto_link_allowed=False,
            auto_link_decision_reason="No se vinculo automaticamente porque hay candidatos similares con confianza comparable.",
        )

    if top.hard_compatible and top.score >= AUTO_MATCH_DIRECT_SCORE:
        top.auto_link_allowed = True
        top.auto_link_decision_reason = "Se vinculo automaticamente porque el score es alto y no hay ambiguedad relevante."
        return MatchDecision(
            activity_id=activity_id,
            status="matched",
            matched_session_id=top.planned_session_id,
            score=top.score,
            confidence=top.confidence,
            confidence_level=top.confidence_level,
            explanations=explanations + ["El score supera 80 y la candidata es practicamente obvia."],
            reasons=top.match_reasons,
            penalties=top.match_penalties,
            candidate_sessions=candidates[:5],
            match_method=_derive_auto_match_method(top, margin),
            auto_link_allowed=True,
            auto_link_decision_reason=top.auto_link_decision_reason,
        )

    if top.hard_compatible and AUTO_MATCH_REVIEW_SCORE <= top.score < AUTO_MATCH_DIRECT_SCORE:
        if len(reasonable_same_day) == 1:
            _append_unique(top.match_reasons, "actividad unica del dia en el mismo deporte")
            top.auto_link_allowed = True
            top.auto_link_decision_reason = "Se vinculo automaticamente porque fue la unica candidata razonable del mismo dia y deporte."
            return MatchDecision(
                activity_id=activity_id,
                status="matched",
                matched_session_id=top.planned_session_id,
                score=top.score,
                confidence=top.confidence,
                confidence_level=top.confidence_level,
                explanations=explanations + ["El score es suficiente y no hubo otra candidata razonable del mismo dia/deporte."],
                reasons=top.match_reasons,
                penalties=top.match_penalties,
                candidate_sessions=candidates[:5],
                match_method=_derive_auto_match_method(top, margin),
                auto_link_allowed=True,
                auto_link_decision_reason=top.auto_link_decision_reason,
            )
        if margin is not None and margin >= AUTO_MATCH_MIN_MARGIN:
            _append_unique(top.match_reasons, f"ventaja clara de {round(margin, 1)} puntos sobre la siguiente candidata")
            top.auto_link_allowed = True
            top.auto_link_decision_reason = "Se vinculo automaticamente por confianza relativa: la mejor candidata supera claramente a la segunda."
            return MatchDecision(
                activity_id=activity_id,
                status="matched",
                matched_session_id=top.planned_session_id,
                score=top.score,
                confidence=top.confidence,
                confidence_level=top.confidence_level,
                explanations=explanations + ["El score quedo entre 65 y 79, pero la diferencia con la segunda candidata es suficiente."],
                reasons=top.match_reasons,
                penalties=top.match_penalties,
                candidate_sessions=candidates[:5],
                match_method=_derive_auto_match_method(top, margin),
                auto_link_allowed=True,
                auto_link_decision_reason=top.auto_link_decision_reason,
            )

    if top.hard_compatible and top.score >= RECOMMENDED_CANDIDATE_SCORE:
        return MatchDecision(
            activity_id=activity_id,
            status="candidate",
            matched_session_id=None,
            score=top.score,
            confidence=top.confidence,
            confidence_level=top.confidence_level,
            explanations=explanations + ["Actividad candidata encontrada, pero no se vinculo automaticamente porque la confianza no fue suficiente."],
            reasons=top.match_reasons,
            penalties=top.match_penalties,
            candidate_sessions=candidates[:5],
            auto_link_allowed=False,
            auto_link_decision_reason=_candidate_hold_reason(top, margin),
        )

    return MatchDecision(
        activity_id=activity_id,
        status="unmatched",
        matched_session_id=None,
        score=top.score,
        confidence=top.confidence,
        confidence_level=top.confidence_level,
        explanations=explanations + ["Ninguna candidata alcanzo un nivel practico de confianza suficiente para auto-vincular."],
        reasons=top.match_reasons,
        penalties=top.match_penalties,
        candidate_sessions=candidates[:5],
        auto_link_allowed=False,
        auto_link_decision_reason="No se vinculo automaticamente porque el score fue bajo o las diferencias practicas fueron demasiado grandes.",
    )


def _date_component_score(
    date_diff_days: int | None,
    weight: float,
    match_reasons: list[str],
    match_penalties: list[str],
) -> float:
    if weight <= 0:
        return 0.0
    if date_diff_days is None:
        _append_unique(match_penalties, "fecha no comparable")
        return 0.0
    if date_diff_days == 0:
        _append_unique(match_reasons, "misma fecha")
        return weight
    if date_diff_days == 1:
        _append_unique(match_reasons, "fecha cercana (+/- 1 dia)")
        _append_unique(match_penalties, "fecha a un dia de distancia")
        return weight * 0.55
    _append_unique(match_penalties, f"fecha fuera de la ventana permitida ({date_diff_days} dias)")
    return 0.0


def _sport_component_score(
    activity: GarminActivity,
    planned_session: PlannedSession,
    weight: float,
    match_reasons: list[str],
    match_penalties: list[str],
) -> float:
    if weight <= 0:
        return 0.0
    activity_family = _sport_family(activity.sport_type)
    session_family = _sport_family(planned_session.sport_type)
    if not activity_family or not session_family:
        _append_unique(match_penalties, "deporte sin clasificacion suficiente")
        return 0.0
    if activity_family != session_family and activity_family != "multisport" and session_family != "multisport":
        _append_unique(match_penalties, "deporte dudoso")
        return 0.0

    _append_unique(match_reasons, "deporte compatible")
    score = weight
    if _normalize_sport(activity.sport_type) == _normalize_sport(planned_session.sport_type):
        _append_unique(match_reasons, "mismo deporte")
    if _normalize_variant(activity.discipline_variant) == _normalize_variant(planned_session.discipline_variant):
        _append_unique(match_reasons, "variante compatible")
    return score


def _duration_component_score(
    expected_duration_min: float | None,
    actual_duration_min: float | None,
    weight: float,
    match_reasons: list[str],
    match_penalties: list[str],
) -> float:
    if weight <= 0 or expected_duration_min in (None, 0) or actual_duration_min is None:
        if weight > 0 and actual_duration_min is None:
            _append_unique(match_penalties, "duracion real no disponible")
        return 0.0
    delta_pct = _relative_delta_pct(expected_duration_min, actual_duration_min)
    if delta_pct <= 10:
        _append_unique(match_reasons, "duracion dentro del 10%")
        return weight
    if delta_pct <= 20:
        _append_unique(match_reasons, "duracion dentro del 20%")
        return weight * 0.82
    if delta_pct <= 35:
        _append_unique(match_reasons, "duracion aceptable")
        _append_unique(match_penalties, _delta_message("duracion", expected_duration_min, actual_duration_min, delta_pct, "min"))
        return weight * 0.55
    _append_unique(match_penalties, _delta_message("duracion", expected_duration_min, actual_duration_min, delta_pct, "min"))
    return weight * 0.15


def _distance_component_score(
    *,
    session_kind: str,
    expected_distance_km: float | None,
    actual_distance_km: float | None,
    weight: float,
    modality_profile: dict[str, Any],
    match_reasons: list[str],
    match_penalties: list[str],
) -> float:
    if weight <= 0:
        return 0.0
    if modality_profile["sport_family"] == "bike" and modality_profile["effective_modality"] in {"indoor", "virtual"}:
        if actual_distance_km in (None, 0):
            _append_unique(match_reasons, "distancia no prioritaria para bici indoor")
            return 0.0
        _append_unique(match_penalties, "distancia secundaria para bici indoor")
        return 0.0
    if modality_profile["sport_family"] == "run" and modality_profile["effective_modality"] == "indoor":
        if expected_distance_km in (None, 0):
            return 0.0
        if actual_distance_km in (None, 0):
            _append_unique(match_penalties, "distancia de cinta no disponible; se priorizaron fecha, deporte y duracion")
            return weight * 0.35
        weight = weight * 0.45
        _append_unique(match_penalties, "distancia de cinta usada con peso bajo")
    if expected_distance_km in (None, 0) or actual_distance_km is None:
        if session_kind == "time_based":
            _append_unique(match_penalties, "distancia no comparable porque la sesion era por tiempo")
        elif actual_distance_km is None:
            _append_unique(match_penalties, "distancia real no disponible")
        return 0.0

    delta_pct = _relative_delta_pct(expected_distance_km, actual_distance_km)
    if delta_pct <= 10:
        _append_unique(match_reasons, "distancia dentro del 10%")
        return weight
    if delta_pct <= 20:
        _append_unique(match_reasons, "distancia dentro del 20%")
        return weight * 0.82
    if delta_pct <= 30:
        _append_unique(match_reasons, "distancia aceptable")
        _append_unique(match_penalties, _delta_message("distancia", expected_distance_km, actual_distance_km, delta_pct, "km"))
        return weight * 0.55
    if session_kind == "time_based":
        _append_unique(match_penalties, "distancia muy distinta, pero la sesion era principalmente por tiempo")
        return weight * 0.3
    _append_unique(match_penalties, _delta_message("distancia", expected_distance_km, actual_distance_km, delta_pct, "km"))
    return weight * 0.1


def _structure_component_score(
    activity: GarminActivity,
    planned_session: PlannedSession,
    *,
    weight: float,
    match_reasons: list[str],
    match_penalties: list[str],
) -> float:
    if weight <= 0:
        return 0.0
    display_blocks = build_session_display_blocks_for_session(planned_session)
    laps = list(activity.laps or [])
    if not display_blocks:
        return 0.0
    if not laps:
        _append_unique(match_penalties, "no hay laps suficientes para comparar la estructura")
        return weight * 0.2

    expected_units = _expected_structure_units(display_blocks)
    if expected_units <= 0:
        return 0.0
    coverage = min(expected_units, len(laps)) / max(expected_units, len(laps))
    repeated = any(isinstance(block, SessionDisplayRepeatBlock) for block in display_blocks)
    work_recovery_like = sum(1 for lap in laps if (lap.duration_sec or 0) > 0)

    if coverage >= 0.9:
        _append_unique(match_reasons, "estructura aproximada bien alineada")
        return weight
    if coverage >= 0.7:
        _append_unique(match_reasons, "estructura parcialmente compatible")
        return weight * 0.75
    if repeated and work_recovery_like >= max(2, expected_units // 2):
        _append_unique(match_reasons, "la actividad muestra una estructura de intervalos aproximada")
        _append_unique(match_penalties, "estructura no exacta")
        return weight * 0.55

    _append_unique(match_penalties, "estructura bastante distinta a la planificada")
    return weight * 0.2


def _intensity_component_score(
    activity: GarminActivity,
    planned_session: PlannedSession,
    *,
    weight: float,
    match_reasons: list[str],
    match_penalties: list[str],
) -> float:
    if weight <= 0:
        return 0.0
    hr_range = _resolve_target_hr_range(planned_session)
    if hr_range is None:
        return 0.0

    activity_hr = activity.avg_hr
    if activity_hr is None:
        _append_unique(match_penalties, "faltan datos de FC media")
        return weight * 0.4

    target_min, target_max = hr_range
    relaxed_min = target_min - 5
    relaxed_max = target_max + _upper_hr_tolerance(planned_session)
    soft_upper = target_max + 12

    if relaxed_min <= activity_hr <= relaxed_max:
        _append_unique(match_reasons, "FC media compatible con objetivo")
        return weight
    if target_min - 8 <= activity_hr <= soft_upper:
        delta = _hr_delta_from_range(activity_hr, target_min, target_max)
        _append_unique(match_reasons, "FC media cercana al objetivo")
        if delta > 0:
            _append_unique(match_penalties, f"FC media {delta} ppm por encima del rango")
        return weight * 0.8

    delta = _hr_delta_from_range(activity_hr, target_min, target_max)
    direction = "por encima" if activity_hr > target_max else "por debajo"
    _append_unique(match_penalties, f"FC media {delta} ppm {direction} del rango")
    return weight * 0.35


def _candidate_default_decision_reason(score: float, hard_compatible: bool) -> str:
    if not hard_compatible:
        return "No es auto-vinculable porque falla alguna condicion dura de deporte, atleta o fecha."
    if score >= AUTO_MATCH_DIRECT_SCORE:
        return "Tiene score alto, pero falta compararlo contra otros candidatos."
    if score >= AUTO_MATCH_REVIEW_SCORE:
        return "Podria auto-vincularse si no aparece otro candidato similar."
    if score >= RECOMMENDED_CANDIDATE_SCORE:
        return "Es una candidata recomendada, pero todavia no tiene confianza suficiente para auto-vincular."
    return "Se considera secundaria porque el score todavia es bajo."


def _candidate_hold_reason(candidate: MatchCandidate, margin: float | None) -> str:
    if not candidate.hard_compatible:
        return "No se vinculo automaticamente porque falla una condicion dura de deporte, atleta o fecha."
    if candidate.score < RECOMMENDED_CANDIDATE_SCORE:
        return "No se vinculo automaticamente porque el score fue bajo."
    if margin is not None and margin < AUTO_MATCH_MIN_MARGIN:
        return "No se vinculo automaticamente porque hay otra candidata cercana en score."
    if any("duracion" in penalty for penalty in candidate.match_penalties):
        return "No se vinculo automaticamente porque la diferencia de duracion sigue siendo grande."
    return "Actividad candidata encontrada, pero no se vinculo automaticamente porque la confianza no fue suficiente."


def _decorate_candidates_for_decision(
    candidates: list[MatchCandidate],
    top: MatchCandidate,
    second: MatchCandidate | None,
) -> None:
    margin = (top.score - second.score) if second is not None else None
    for candidate in candidates:
        candidate.auto_link_allowed = False
        candidate.auto_link_decision_reason = _candidate_default_decision_reason(candidate.score, candidate.hard_compatible)
    if second is not None and margin is not None and margin < AMBIGUOUS_MARGIN and top.score >= AMBIGUOUS_MIN_SCORE and second.score >= AMBIGUOUS_MIN_SCORE:
        top.auto_link_decision_reason = "No se auto-vinculo porque hay otro candidato similar."
        second.auto_link_decision_reason = "No se auto-vinculo porque hay otro candidato similar."


def _derive_auto_match_method(candidate: MatchCandidate, margin: float | None) -> str:
    if candidate.score >= AUTO_MATCH_DIRECT_SCORE:
        return "same_day_high_confidence"
    if margin is not None and margin >= AUTO_MATCH_MIN_MARGIN:
        return "same_day_relative_confidence"
    return "same_day_unique_candidate"


def _build_match_explanation(decision: MatchDecision) -> str:
    parts = list(decision.explanations)
    if decision.auto_link_decision_reason:
        parts.append(decision.auto_link_decision_reason)
    if decision.reasons:
        parts.append("Razones: " + ", ".join(decision.reasons[:5]) + ".")
    if decision.penalties:
        parts.append("Penalizaciones: " + ", ".join(decision.penalties[:4]) + ".")
    return " ".join(part for part in parts if part)


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
            selectinload(PlannedSession.athlete),
        )
    )
    if training_plan_id is not None:
        statement = statement.where(TrainingDay.training_plan_id == training_plan_id)
    sessions = list(db.scalars(statement).all())
    filtered: list[PlannedSession] = []
    for session in sessions:
        if session.activity_match and session.activity_match.garmin_activity_id_fk != activity.id:
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
            selectinload(PlannedSession.athlete),
        )
    )
    return db.scalar(statement)


def _activity_local_date(activity: GarminActivity) -> date | None:
    if activity.start_time is None:
        return None
    return to_local_date(activity.start_time, athlete=activity.athlete)


def _activity_local_datetime(value: datetime) -> datetime:
    local_value = to_local_datetime(value)
    if local_value is None:
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return local_value


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


def _detect_session_kind(
    planned_session: PlannedSession,
    expected_duration_min: float | None,
    expected_distance_km: float | None,
) -> str:
    blocks = build_session_display_blocks_for_session(planned_session)
    if _looks_structured_session(planned_session, blocks):
        return "structured"

    duration_steps = 0
    distance_steps = 0
    for step in _expand_simple_steps(blocks):
        if step.duration_sec:
            duration_steps += 1
        if step.distance_m:
            distance_steps += 1

    if distance_steps > duration_steps and expected_distance_km not in (None, 0):
        return "distance_based"
    if duration_steps > 0:
        return "time_based"
    if expected_distance_km not in (None, 0) and expected_duration_min in (None, 0):
        return "distance_based"
    return "time_based"


def _looks_structured_session(planned_session: PlannedSession, blocks: list[SessionDisplayBlock]) -> bool:
    if (planned_session.session_type or "").strip().lower() in {"interval", "intervals", "repeats", "fartlek"}:
        return True
    if len(blocks) >= 3:
        return True
    if any(isinstance(block, SessionDisplayRepeatBlock) for block in blocks):
        return True
    target_markers = {getattr(step, "target_type", None) for step in _expand_simple_steps(blocks)}
    return len([marker for marker in target_markers if marker]) >= 2


def _expand_simple_steps(blocks: list[SessionDisplayBlock]) -> list[SessionDisplaySimpleStep]:
    simple_steps: list[SessionDisplaySimpleStep] = []
    for block in blocks:
        if isinstance(block, SessionDisplayRepeatBlock):
            simple_steps.extend(block.steps)
        else:
            simple_steps.append(block)
    return simple_steps


def _expected_structure_units(blocks: list[SessionDisplayBlock]) -> int:
    total = 0
    for block in blocks:
        if isinstance(block, SessionDisplayRepeatBlock):
            total += max(1, len(block.steps)) * max(1, block.repeat_count)
        else:
            total += 1
    return total


def _resolve_target_hr_range(planned_session: PlannedSession) -> tuple[int, int] | None:
    blocks = build_session_display_blocks_for_session(planned_session)
    explicit_ranges = [
        (step.target_hr_min, step.target_hr_max)
        for step in _expand_simple_steps(blocks)
        if step.target_type == "hr" and (step.target_hr_min is not None or step.target_hr_max is not None)
    ]
    if explicit_ranges:
        minimums = [value for value, _ in explicit_ranges if value is not None]
        maximums = [value for _, value in explicit_ranges if value is not None]
        if minimums or maximums:
            return (
                min(minimums) if minimums else min(maximums),
                max(maximums) if maximums else max(minimums),
            )

    if planned_session.target_hr_zone:
        zone_range = _lookup_zone_range(planned_session, planned_session.target_hr_zone)
        if zone_range is not None:
            return zone_range

    for step in _expand_simple_steps(blocks):
        if step.target_hr_zone:
            zone_range = _lookup_zone_range(planned_session, step.target_hr_zone)
            if zone_range is not None:
                return zone_range
    return None


def _lookup_zone_range(planned_session: PlannedSession, zone_name: str) -> tuple[int, int] | None:
    athlete = getattr(planned_session, "athlete", None)
    payload = load_zone_payload(getattr(athlete, "hr_zones_json", None))
    if not payload:
        return None

    normalized_zone = str(zone_name).strip()
    family = _sport_family(planned_session.sport_type)
    keys_to_try = []
    if family == "run":
        keys_to_try.extend(["running", "general"])
    elif family == "bike":
        keys_to_try.extend(["cycling", "general"])
    else:
        keys_to_try.append("general")

    for payload_key in keys_to_try:
        for row in payload.get(payload_key, []):
            if str(row.get("name") or "").strip().lower() != normalized_zone.lower():
                continue
            minimum = _safe_int(row.get("min"))
            maximum = _safe_int(row.get("max"))
            if minimum is None and maximum is None:
                continue
            return (minimum or maximum or 0, maximum or minimum or 0)
    return None


def _confidence_level_for_score(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 80:
        return "high"
    if score >= 65:
        return "medium"
    return "low"


def _relative_delta_pct(expected: float, actual: float) -> float:
    if expected == 0:
        return 100.0
    return abs(actual - expected) / expected * 100.0


def _delta_message(label: str, expected: float, actual: float, delta_pct: float, unit: str) -> str:
    direction = "mayor" if actual > expected else "menor"
    return f"{label} {round(delta_pct)}% {direction} a la planificada"


def _upper_hr_tolerance(planned_session: PlannedSession) -> int:
    session_type = (planned_session.session_type or "").strip().lower()
    if session_type in {"easy", "base", "recovery"}:
        return 8
    return 6


def _hr_delta_from_range(activity_hr: int, target_min: int, target_max: int) -> int:
    if activity_hr < target_min:
        return target_min - activity_hr
    if activity_hr > target_max:
        return activity_hr - target_max
    return 0


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _match_modality_profile(activity: GarminActivity, planned_session: PlannedSession) -> dict[str, Any]:
    planned_modality = normalize_modality(getattr(planned_session, "modality", None))
    activity_modality = normalize_modality(getattr(activity, "modality", None))
    effective_modality = preferred_modality(activity_modality, planned_modality)
    explicit_match = bool(planned_modality and activity_modality and planned_modality == activity_modality)
    explicit_mismatch = bool(
        planned_modality
        and activity_modality
        and planned_modality != "unknown"
        and activity_modality != "unknown"
        and planned_modality != activity_modality
    )
    return {
        "planned_modality": planned_modality,
        "activity_modality": activity_modality,
        "effective_modality": effective_modality,
        "explicit_match": explicit_match,
        "explicit_mismatch": explicit_mismatch,
        "sport_family": _sport_family(planned_session.sport_type or activity.sport_type),
        "has_planned_incline": _planned_session_has_incline(planned_session),
    }


def _score_weights_for_profile(session_kind: str, modality_profile: dict[str, Any]) -> dict[str, float]:
    weights = dict(SCORE_WEIGHTS[session_kind])
    if modality_profile["sport_family"] == "bike" and modality_profile["effective_modality"] in {"indoor", "virtual"}:
        weights["distance"] = 0.0
        weights["duration"] = max(weights["duration"], 30.0)
        weights["intensity"] = max(weights["intensity"], 20.0)
    elif modality_profile["sport_family"] == "run" and modality_profile["effective_modality"] == "indoor":
        weights["distance"] = 3.0 if modality_profile.get("has_planned_incline") else min(weights["distance"], 8.0)
        weights["duration"] = max(weights["duration"], 20.0)
        weights["intensity"] = max(weights["intensity"], 15.0 if modality_profile.get("has_planned_incline") else 12.0)
    total = sum(weights.values())
    if total > 100.0:
        scale = 100.0 / total
        weights = {key: round(value * scale, 2) for key, value in weights.items()}
    return weights


def _planned_session_has_incline(planned_session: PlannedSession) -> bool:
    for step in list(getattr(planned_session, "planned_session_steps", []) or []):
        if getattr(step, "incline_pct", None) is not None:
            return True
    return False
