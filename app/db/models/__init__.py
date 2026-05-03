"""SQLAlchemy models package."""

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.activity_weather import ActivityWeather
from app.db.models.analysis_report import AnalysisReport
from app.db.models.analysis_report_item import AnalysisReportItem
from app.db.models.athlete import Athlete
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.garmin_activity_lap import GarminActivityLap
from app.db.models.garmin_account import GarminAccount
from app.db.models.goal import Goal
from app.db.models.planned_session import PlannedSession
from app.db.models.planned_session_step import PlannedSessionStep
from app.db.models.health_ai_analysis import HealthAiAnalysis
from app.db.models.health_sync_state import HealthSyncState
from app.db.models.session_group import SessionGroup
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.session_template import SessionTemplate
from app.db.models.session_template_step import SessionTemplateStep
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.models.weekly_analysis import WeeklyAnalysis

__all__ = [
    "ActivitySessionMatch",
    "ActivityWeather",
    "AnalysisReport",
    "AnalysisReportItem",
    "Athlete",
    "DailyHealthMetric",
    "GarminActivity",
    "GarminActivityLap",
    "GarminAccount",
    "Goal",
    "HealthAiAnalysis",
    "HealthSyncState",
    "TrainingPlan",
    "TrainingDay",
    "PlannedSession",
    "PlannedSessionStep",
    "SessionGroup",
    "SessionAnalysis",
    "SessionTemplate",
    "SessionTemplateStep",
    "WeeklyAnalysis",
]
