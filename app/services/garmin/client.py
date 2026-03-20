from __future__ import annotations

from datetime import date
import logging

from garminconnect import Garmin


logger = logging.getLogger(__name__)


class GarminClient:
    def __init__(self, api: Garmin) -> None:
        self.api = api

    def get_recent_activities(self, limit: int = 20) -> list[dict]:
        data = self.api.get_activities(start=0, limit=limit)
        if isinstance(data, list):
            return data
        return list(data or [])

    def get_activity_summary(self, activity_id: int | str) -> dict:
        return self.api.get_activity(str(activity_id)) or {}

    def get_activity_details(self, activity_id: int | str) -> dict:
        return self.api.get_activity_details(str(activity_id)) or {}

    def get_activity_splits(self, activity_id: int | str) -> list[dict]:
        data = self.api.get_activity_splits(str(activity_id)) or []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("lapDTOs", "splits", "detailedSplits"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    def get_health_payloads(self, metric_date: date) -> dict[str, object]:
        date_str = metric_date.isoformat()
        return {
            "daily_summary": self._safe_call("daily_summary", lambda: self.api.get_stats(date_str), {}),
            "sleep": self._safe_call("sleep", lambda: self.api.get_sleep_data(date_str), {}),
            "stress": self._safe_call("stress", lambda: self.api.get_stress_data(date_str), {}),
            "body_battery": self._safe_call("body_battery", lambda: self.api.get_body_battery(date_str, date_str), []),
            "hrv": self._safe_call("hrv", lambda: self.api.get_hrv_data(date_str), {}),
            "resting_hr": self._safe_call("resting_hr", lambda: self.api.get_rhr_day(date_str), {}),
            "respiration": self._safe_call("respiration", lambda: self.api.get_respiration_data(date_str), {}),
            "spo2": self._safe_call("spo2", lambda: self.api.get_spo2_data(date_str), {}),
            "max_metrics": self._safe_call("max_metrics", lambda: self.api.get_max_metrics(date_str), {}),
            "training_readiness": self._safe_call("training_readiness", lambda: self.api.get_training_readiness(date_str), {}),
        }

    def _safe_call(self, name: str, func, default: object) -> object:
        try:
            return func() or default
        except Exception:
            logger.warning("Garmin %s payload was unavailable for this sync.", name, exc_info=True)
            return default
