from __future__ import annotations

import json
from datetime import date
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


class WeatherClientError(Exception):
    """Raised when the weather provider cannot return usable data."""


class OpenMeteoClient:
    base_url = "https://archive-api.open-meteo.com/v1/archive"
    provider_name = "open-meteo"
    hourly_fields = (
        "temperature_2m",
        "apparent_temperature",
        "relative_humidity_2m",
        "dew_point_2m",
        "wind_speed_10m",
        "wind_direction_10m",
        "surface_pressure",
        "precipitation",
    )

    def fetch_hourly_history(
        self,
        *,
        latitude: float,
        longitude: float,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        query = urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "hourly": ",".join(self.hourly_fields),
                "timezone": "auto",
            }
        )
        url = f"{self.base_url}?{query}"
        try:
            with urlopen(url, timeout=20) as response:
                payload = response.read().decode("utf-8")
        except Exception as exc:
            raise WeatherClientError(f"Weather request failed: {exc}") from exc

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise WeatherClientError("Weather provider returned invalid JSON.") from exc

        if not isinstance(data, dict):
            raise WeatherClientError("Weather provider returned an unexpected payload.")
        if "hourly" not in data or not isinstance(data["hourly"], dict):
            raise WeatherClientError("Weather provider returned no hourly data.")
        return data
