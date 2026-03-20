from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.daily_health_metric import DailyHealthMetric


def get_health_metrics(db: Session) -> list[DailyHealthMetric]:
    statement = select(DailyHealthMetric).order_by(
        DailyHealthMetric.metric_date.desc(),
        DailyHealthMetric.id.desc(),
    )
    return list(db.scalars(statement).all())


def get_health_metric(db: Session, metric_id: int) -> DailyHealthMetric | None:
    statement = (
        select(DailyHealthMetric)
        .where(DailyHealthMetric.id == metric_id)
        .options(selectinload(DailyHealthMetric.athlete))
    )
    return db.scalar(statement)
