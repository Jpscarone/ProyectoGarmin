from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.schemas.athlete import AthleteCreate, AthleteRead, AthleteUpdate
from app.services.athlete_service import (
    ATHLETE_STATUS_ACTIVE,
    create_athlete,
    delete_athlete,
    get_active_athletes,
    get_athlete,
    get_athletes,
    update_athlete,
)
from app.services.athlete_context import clear_current_athlete, set_current_athlete, set_current_training_plan
from app.services.training_plan_service import select_default_training_plan
from app.services.athlete_zone_service import (
    build_zone_form_rows,
    recalculate_athlete_zones,
    update_athlete_zones_manual,
    use_garmin_zones,
    zone_source_label,
)
from app.services.garmin.auth import GarminServiceError, get_garmin_auth_diagnostics
from app.services.garmin.profile_sync import apply_garmin_changes, build_athlete_garmin_comparison, load_zone_payload, compare_athlete_with_garmin
from app.web.templates import build_templates


router = APIRouter(prefix="/athletes", tags=["athletes"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@router.get("", response_model=list[AthleteRead])
def list_athletes(request: Request, db: Session = Depends(get_db)):
    athletes = get_athletes(db)
    if _wants_html(request):
        settings = get_settings()
        return templates.TemplateResponse(
            request=request,
            name="athletes/list.html",
            context={
                "athletes": athletes,
                "garmin_auth_diagnostics": get_garmin_auth_diagnostics(settings),
            },
        )
    return athletes


@router.get("/create", response_class=HTMLResponse)
def create_athlete_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="athletes/create.html",
        context={"athlete": None},
    )


@router.get("/select", response_class=HTMLResponse)
def select_athlete_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="athletes/select.html",
        context={
            "active_athletes": get_active_athletes(db),
            "status_message": request.query_params.get("status_message"),
            "error_message": request.query_params.get("error"),
        },
    )


@router.post("/select")
def select_athlete_endpoint(
    request: Request,
    athlete_id: int = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    athlete = get_athlete(db, athlete_id)
    if athlete is None or athlete.status != ATHLETE_STATUS_ACTIVE:
        clear_current_athlete(request)
        return RedirectResponse(url="/athletes/select?error=El%20atleta%20no%20esta%20activo", status_code=303)

    set_current_athlete(request, athlete.id)
    default_plan = select_default_training_plan(db, athlete_id=athlete.id)
    set_current_training_plan(request, default_plan.id if default_plan else None)
    if default_plan is not None:
        return RedirectResponse(url=f"/training_plans/{default_plan.id}/calendar?athlete_id={athlete.id}", status_code=303)
    return RedirectResponse(url=f"/training_plans?athlete_id={athlete.id}", status_code=303)


@router.get("/{athlete_id}/plans")
def athlete_plans_alias(request: Request, athlete_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    athlete = get_athlete(db, athlete_id)
    if athlete is None or athlete.status != ATHLETE_STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")
    set_current_athlete(request, athlete.id)
    return RedirectResponse(url=f"/training_plans?athlete_id={athlete.id}", status_code=303)


@router.get("/{athlete_id}/activities")
def athlete_activities_alias(request: Request, athlete_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    athlete = get_athlete(db, athlete_id)
    if athlete is None or athlete.status != ATHLETE_STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")
    set_current_athlete(request, athlete.id)
    return RedirectResponse(url=f"/activities?athlete_id={athlete.id}", status_code=303)


@router.get("/{athlete_id}/health")
def athlete_health_alias(request: Request, athlete_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    athlete = get_athlete(db, athlete_id)
    if athlete is None or athlete.status != ATHLETE_STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")
    set_current_athlete(request, athlete.id)
    return RedirectResponse(url=f"/health?athlete_id={athlete.id}", status_code=303)


@router.get("/{athlete_id}/training-plans/{training_plan_id}/calendar")
def athlete_calendar_alias(
    request: Request,
    athlete_id: int,
    training_plan_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    athlete = get_athlete(db, athlete_id)
    if athlete is None or athlete.status != ATHLETE_STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")
    set_current_athlete(request, athlete.id)
    set_current_training_plan(request, training_plan_id)
    query = request.url.query
    suffix = f"&{query}" if query else ""
    return RedirectResponse(
        url=f"/training_plans/{training_plan_id}/calendar?athlete_id={athlete.id}{suffix}",
        status_code=303,
    )


@router.get("/{athlete_id}", response_model=AthleteRead)
def read_athlete(request: Request, athlete_id: int, db: Session = Depends(get_db)):
    athlete = get_athlete(db, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")
    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="athletes/detail.html",
            context={
                "athlete": athlete,
                "comparison": build_athlete_garmin_comparison(athlete),
                "hr_zones": load_zone_payload(athlete.hr_zones_json),
                "power_zones": load_zone_payload(athlete.power_zones_json),
                "pace_zones": load_zone_payload(athlete.pace_zones_json),
                "rpe_zones": load_zone_payload(athlete.rpe_zones_json),
                "source_hr_zones_label": zone_source_label(athlete.source_hr_zones),
                "source_power_zones_label": zone_source_label(athlete.source_power_zones),
                "source_pace_zones_label": zone_source_label(athlete.source_pace_zones),
                "source_rpe_zones_label": zone_source_label(athlete.source_rpe_zones),
                "status_message": request.query_params.get("status_message"),
                "error_message": request.query_params.get("error"),
                "garmin_auth_diagnostics": get_garmin_auth_diagnostics(get_settings()),
            },
        )
    return athlete


@router.get("/{athlete_id}/edit", response_class=HTMLResponse)
def edit_athlete_page(athlete_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    athlete = get_athlete(db, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")

    return templates.TemplateResponse(
        request=request,
        name="athletes/edit.html",
        context={"athlete": athlete},
    )


@router.get("/{athlete_id}/zones/edit", response_class=HTMLResponse)
def edit_athlete_zones_page(athlete_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    athlete = get_athlete(db, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")

    zone_rows = build_zone_form_rows(athlete)
    return templates.TemplateResponse(
        request=request,
        name="athletes/zones_edit.html",
        context={
            "athlete": athlete,
            "hr_rows": zone_rows["hr_rows"],
            "power_rows": zone_rows["power_rows"],
            "pace_rows": zone_rows["pace_rows"],
            "rpe_rows": zone_rows["rpe_rows"],
            "status_message": request.query_params.get("status_message"),
            "error_message": request.query_params.get("error"),
        },
    )


@router.post("/{athlete_id}/zones/edit")
async def edit_athlete_zones_endpoint(athlete_id: int, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    athlete = get_athlete(db, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")

    form = await request.form()
    hr_rows = _zone_rows_from_form(form, "hr")
    power_rows = _zone_rows_from_form(form, "power")
    pace_rows = _pace_zone_rows_from_form(form, "pace")
    rpe_rows = _rpe_zone_rows_from_form(form, "rpe")
    try:
        updated = update_athlete_zones_manual(db, athlete, hr_rows, power_rows, pace_rows, rpe_rows)
        message = "Se actualizaron " + ", ".join(updated) + "."
        return RedirectResponse(url=f"/athletes/{athlete_id}?status_message={quote(message)}", status_code=303)
    except ValueError as exc:
        return RedirectResponse(url=f"/athletes/{athlete_id}/zones/edit?error={quote(str(exc))}", status_code=303)


@router.post("", response_model=AthleteRead, status_code=status.HTTP_201_CREATED)
def create_athlete_endpoint(athlete_in: AthleteCreate, db: Session = Depends(get_db)) -> AthleteRead:
    return create_athlete(db, athlete_in)


@router.put("/{athlete_id}", response_model=AthleteRead)
def update_athlete_endpoint(
    athlete_id: int,
    athlete_in: AthleteUpdate,
    db: Session = Depends(get_db),
) -> AthleteRead:
    athlete = get_athlete(db, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")
    return update_athlete(db, athlete, athlete_in)


@router.delete("/{athlete_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_athlete_endpoint(athlete_id: int, db: Session = Depends(get_db)) -> Response:
    athlete = get_athlete(db, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")
    delete_athlete(db, athlete)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{athlete_id}/compare-garmin")
def compare_athlete_garmin_endpoint(athlete_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    athlete = get_athlete(db, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")

    try:
        compare_athlete_with_garmin(db, athlete, get_settings())
    except GarminServiceError as exc:
        return RedirectResponse(url=f"/athletes/{athlete_id}?error={quote(str(exc))}", status_code=303)

    return RedirectResponse(
        url=f"/athletes/{athlete_id}?status_message={quote('Comparacion con Garmin actualizada.')}",
        status_code=303,
    )


@router.post("/{athlete_id}/apply-garmin")
def apply_athlete_garmin_endpoint(
    athlete_id: int,
    scope: str = Form(default="all"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    athlete = get_athlete(db, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")

    try:
        applied_blocks = apply_garmin_changes(db, athlete, scope)
        message = "Se aplicaron cambios de Garmin en " + ", ".join(applied_blocks) + "."
        return RedirectResponse(url=f"/athletes/{athlete_id}?status_message={quote(message)}", status_code=303)
    except ValueError as exc:
        return RedirectResponse(url=f"/athletes/{athlete_id}?error={quote(str(exc))}", status_code=303)


@router.post("/{athlete_id}/zones/use-garmin")
def use_athlete_garmin_zones_endpoint(athlete_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    athlete = get_athlete(db, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")

    try:
        updated = use_garmin_zones(db, athlete)
        message = "Se aplicaron " + ", ".join(updated) + " desde Garmin."
        return RedirectResponse(url=f"/athletes/{athlete_id}?status_message={quote(message)}", status_code=303)
    except ValueError as exc:
        return RedirectResponse(url=f"/athletes/{athlete_id}?error={quote(str(exc))}", status_code=303)


@router.post("/{athlete_id}/zones/recalculate")
def recalculate_athlete_zones_endpoint(athlete_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    athlete = get_athlete(db, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found")

    try:
        updated = recalculate_athlete_zones(db, athlete)
        message = "Se recalcularon " + ", ".join(updated) + "."
        return RedirectResponse(url=f"/athletes/{athlete_id}?status_message={quote(message)}", status_code=303)
    except ValueError as exc:
        return RedirectResponse(url=f"/athletes/{athlete_id}?error={quote(str(exc))}", status_code=303)


def _zone_rows_from_form(form, prefix: str) -> list[dict[str, int | None]]:
    rows: list[dict[str, int | None]] = []
    for index in range(1, 6):
        minimum = _optional_int(form.get(f"{prefix}_z{index}_min"))
        maximum = _optional_int(form.get(f"{prefix}_z{index}_max"))
        rows.append({"min": minimum, "max": maximum})
    return rows


def _pace_zone_rows_from_form(form, prefix: str) -> list[dict[str, int | None]]:
    rows: list[dict[str, int | None]] = []
    for index in range(1, 6):
        minimum = _pace_to_seconds(form.get(f"{prefix}_z{index}_min"))
        maximum = _pace_to_seconds(form.get(f"{prefix}_z{index}_max"))
        rows.append({"min": minimum, "max": maximum})
    return rows


def _rpe_zone_rows_from_form(form, prefix: str) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    for index in range(1, 6):
        rows.append({"label": _optional_text(form.get(f"{prefix}_z{index}_label"))})
    return rows


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _pace_to_seconds(value: object) -> int | None:
    text = _optional_text(value)
    if text is None:
        return None
    parts = text.split(":")
    if len(parts) != 2:
        return None
    try:
        minutes = int(parts[0])
        seconds = int(parts[1])
    except ValueError:
        return None
    if minutes < 0 or seconds < 0 or seconds > 59:
        return None
    return minutes * 60 + seconds
