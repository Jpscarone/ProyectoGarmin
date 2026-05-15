from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings


DEFAULT_TIMEZONE = "America/Argentina/Buenos_Aires"


def _fixed_default_timezone():
    return timezone(timedelta(hours=-3), name=DEFAULT_TIMEZONE)


def get_app_timezone() -> tzinfo:
    timezone_name = get_settings().app_timezone or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return _fixed_default_timezone()


def get_athlete_timezone(athlete: object | None) -> tzinfo:
    timezone_name = getattr(athlete, "timezone", None) or get_settings().app_timezone or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(str(timezone_name))
    except ZoneInfoNotFoundError:
        if str(timezone_name) == DEFAULT_TIMEZONE:
            return _fixed_default_timezone()
        return get_app_timezone()


def get_athlete_timezone_name(athlete: object | None) -> str:
    return getattr(get_athlete_timezone(athlete), "key", None) or str(get_athlete_timezone(athlete))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_local(*, athlete: object | None = None) -> datetime:
    return now_utc().astimezone(get_athlete_timezone(athlete))


def today_local(*, athlete: object | None = None) -> date:
    return now_local(athlete=athlete).date()


def ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def to_local_datetime(dt: datetime | None, *, athlete: object | None = None) -> datetime | None:
    if dt is None:
        return None
    return ensure_aware(dt).astimezone(get_athlete_timezone(athlete))


def to_local_date(dt: datetime | None, *, athlete: object | None = None) -> date | None:
    local_dt = to_local_datetime(dt, athlete=athlete)
    return local_dt.date() if local_dt is not None else None


def format_local_datetime(
    dt: datetime | None,
    *,
    athlete: object | None = None,
    fmt: str = "%d/%m/%Y %H:%M",
    empty: str = "-",
) -> str:
    local_dt = to_local_datetime(dt, athlete=athlete)
    if local_dt is None:
        return empty
    return local_dt.strftime(fmt)


def local_date_start_utc(reference_date: date, *, athlete: object | None = None) -> datetime:
    return datetime.combine(reference_date, time.min, tzinfo=get_athlete_timezone(athlete)).astimezone(timezone.utc)


def local_date_range_utc_bounds(
    date_from: date,
    date_to: date,
    *,
    athlete: object | None = None,
    days_before: int = 0,
    days_after: int = 0,
) -> tuple[datetime, datetime]:
    start_date = date_from if date_from <= date_to else date_to
    end_date = date_to if date_to >= date_from else date_from
    start_dt = local_date_start_utc(start_date.fromordinal(start_date.toordinal() - max(days_before, 0)), athlete=athlete)
    end_dt = local_date_start_utc(end_date.fromordinal(end_date.toordinal() + max(days_after, 0) + 1), athlete=athlete)
    return start_dt, end_dt
