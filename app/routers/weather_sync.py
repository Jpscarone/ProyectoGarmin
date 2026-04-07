from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.garmin_activity_service import get_activity
from app.services.weather.weather_service import ActivityWeatherSyncError, sync_weather_for_activity


router = APIRouter(prefix="/sync/weather", tags=["weather_sync"])


@router.get("/activity/{activity_id}")
def sync_activity_weather(
    activity_id: int,
    return_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    activity = get_activity(db, activity_id)
    if activity is None:
        return RedirectResponse(
            url="/activities?weather_status=Actividad%20no%20encontrada.",
            status_code=303,
        )

    try:
        result = sync_weather_for_activity(db, activity)
        message = result.message
    except ActivityWeatherSyncError as exc:
        message = str(exc)
    except Exception as exc:
        message = f"La sincronizacion de clima fallo de forma inesperada: {exc}"

    target = (return_to or "").strip().lower()
    if target == "list":
        redirect_url = f"/activities?weather_status={quote(message)}"
    else:
        redirect_url = f"/activities/{activity_id}?weather_status={quote(message)}"

    return RedirectResponse(url=redirect_url, status_code=303)
