from __future__ import annotations

from typing import Any

import httpx
from mcp.server.fastmcp.exceptions import ToolError

try:
    from .settings import Settings
except ImportError:
    from settings import Settings


class TrainingAppApiClient:
    def __init__(self, settings: Settings, *, async_client_factory: type[httpx.AsyncClient] = httpx.AsyncClient):
        self.settings = settings
        self.async_client_factory = async_client_factory

    async def get_athletes(self) -> dict[str, Any] | list[dict[str, Any]]:
        return await self._get_json("/api/mcp/athletes")

    async def get_recent_activities(self, *, athlete_id: int, limit: int = 10) -> dict[str, Any]:
        return await self._get_json(
            "/api/mcp/activities/recent",
            params={
                "athlete_id": str(int(athlete_id)),
                "limit": str(max(1, int(limit))),
            },
        )

    async def get_activity_detail(self, *, athlete_id: int, activity_id: int) -> dict[str, Any]:
        return await self._get_json(
            f"/api/mcp/activities/{int(activity_id)}",
            params={"athlete_id": str(int(athlete_id))},
        )

    async def get_health_summary(self, *, athlete_id: int) -> dict[str, Any]:
        return await self._get_json(
            "/api/mcp/health/summary",
            params={"athlete_id": str(int(athlete_id))},
        )

    async def get_latest_weekly_analysis(self, *, athlete_id: int) -> dict[str, Any]:
        return await self._get_json(
            "/api/mcp/weekly/latest",
            params={"athlete_id": str(int(athlete_id))},
        )

    async def get_training_status(self, *, athlete_id: int) -> dict[str, Any]:
        return await self._get_json(
            "/api/mcp/training/status",
            params={"athlete_id": str(int(athlete_id))},
        )

    async def get_day_plan(self, *, athlete_id: int, date: str) -> dict[str, Any]:
        return await self._get_json(
            "/api/mcp/training/day-plan",
            params={
                "athlete_id": str(int(athlete_id)),
                "date": date,
            },
        )

    async def get_week_plan(
        self,
        *,
        athlete_id: int,
        week_start_date: str | None = None,
        include_completed: bool = True,
    ) -> dict[str, Any]:
        params = {
            "athlete_id": str(int(athlete_id)),
            "include_completed": "true" if include_completed else "false",
        }
        if week_start_date:
            params["week_start_date"] = week_start_date
        return await self._get_json(
            "/api/mcp/training/week-plan",
            params=params,
        )

    async def identify_me(self, *, access_code: str) -> dict[str, Any]:
        return await self._get_json(
            "/api/mcp/me/identify",
            params={"access_code": access_code},
        )

    async def get_my_recent_activities(self, *, access_code: str, limit: int = 10) -> dict[str, Any]:
        return await self._get_json(
            "/api/mcp/me/activities/recent",
            params={
                "access_code": access_code,
                "limit": str(max(1, int(limit))),
            },
        )

    async def get_my_health_summary(self, *, access_code: str) -> dict[str, Any]:
        return await self._get_json(
            "/api/mcp/me/health/summary",
            params={"access_code": access_code},
        )

    async def get_my_training_status(self, *, access_code: str) -> dict[str, Any]:
        return await self._get_json(
            "/api/mcp/me/training/status",
            params={"access_code": access_code},
        )

    async def get_my_day_plan(self, *, access_code: str, date: str) -> dict[str, Any]:
        return await self._get_json(
            "/api/mcp/me/day-plan",
            params={
                "access_code": access_code,
                "date": date,
            },
        )

    async def get_my_week_plan(
        self,
        *,
        access_code: str,
        week_start_date: str | None = None,
        include_completed: bool = True,
    ) -> dict[str, Any]:
        params = {
            "access_code": access_code,
            "include_completed": "true" if include_completed else "false",
        }
        if week_start_date:
            params["week_start_date"] = week_start_date
        return await self._get_json(
            "/api/mcp/me/week-plan",
            params=params,
        )

    async def get_day_overview(self, *, athlete_id: int, date: str) -> dict[str, Any]:
        return await self._get_json(
            "/api/mcp/training/day-overview",
            params={
                "athlete_id": str(int(athlete_id)),
                "date": date,
            },
        )

    async def get_my_day_overview(self, *, access_code: str, date: str) -> dict[str, Any]:
        return await self._get_json(
            "/api/mcp/me/day-overview",
            params={
                "access_code": access_code,
                "date": date,
            },
        )

    async def compare_planned_vs_done(
        self,
        *,
        athlete_id: int,
        date: str | None = None,
        activity_id: int | None = None,
        planned_session_id: int | None = None,
    ) -> dict[str, Any]:
        params = {"athlete_id": str(int(athlete_id))}
        if date:
            params["date"] = date
        if activity_id is not None:
            params["activity_id"] = str(int(activity_id))
        if planned_session_id is not None:
            params["planned_session_id"] = str(int(planned_session_id))
        return await self._get_json(
            "/api/mcp/compare/planned-vs-done",
            params=params,
        )

    async def get_next_session_recommendation(
        self,
        *,
        athlete_id: int,
        reference_date: str | None = None,
        planned_session_id: int | None = None,
    ) -> dict[str, Any]:
        params = {"athlete_id": str(int(athlete_id))}
        if reference_date:
            params["reference_date"] = reference_date
        if planned_session_id is not None:
            params["planned_session_id"] = str(int(planned_session_id))
        return await self._get_json(
            "/api/mcp/training/next-session-recommendation",
            params=params,
        )

    async def get_week_load_summary(
        self,
        *,
        athlete_id: int,
        week_start_date: str | None = None,
        compare_previous: bool = True,
    ) -> dict[str, Any]:
        params = {
            "athlete_id": str(int(athlete_id)),
            "compare_previous": "true" if compare_previous else "false",
        }
        if week_start_date:
            params["week_start_date"] = week_start_date
        return await self._get_json(
            "/api/mcp/training/week-load-summary",
            params=params,
        )

    async def get_session_analysis_payload(
        self,
        *,
        athlete_id: int,
        planned_session_id: int | None = None,
        activity_id: int | None = None,
        date: str | None = None,
    ) -> dict[str, Any]:
        params = {"athlete_id": str(int(athlete_id))}
        if planned_session_id is not None:
            params["planned_session_id"] = str(int(planned_session_id))
        if activity_id is not None:
            params["activity_id"] = str(int(activity_id))
        if date:
            params["date"] = date
        return await self._get_json(
            "/api/mcp/analysis/session-payload",
            params=params,
        )

    async def compare_my_planned_vs_done(
        self,
        *,
        access_code: str,
        date: str | None = None,
    ) -> dict[str, Any]:
        params = {"access_code": access_code}
        if date:
            params["date"] = date
        return await self._get_json(
            "/api/mcp/me/compare/planned-vs-done",
            params=params,
        )

    async def get_my_next_session_recommendation(
        self,
        *,
        access_code: str,
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        params = {"access_code": access_code}
        if reference_date:
            params["reference_date"] = reference_date
        return await self._get_json(
            "/api/mcp/me/training/next-session-recommendation",
            params=params,
        )

    async def get_my_week_load_summary(
        self,
        *,
        access_code: str,
        week_start_date: str | None = None,
        compare_previous: bool = True,
    ) -> dict[str, Any]:
        params = {
            "access_code": access_code,
            "compare_previous": "true" if compare_previous else "false",
        }
        if week_start_date:
            params["week_start_date"] = week_start_date
        return await self._get_json(
            "/api/mcp/me/training/week-load-summary",
            params=params,
        )

    async def get_my_session_analysis_payload(
        self,
        *,
        access_code: str,
        planned_session_id: int | None = None,
        activity_id: int | None = None,
        date: str | None = None,
    ) -> dict[str, Any]:
        params = {"access_code": access_code}
        if planned_session_id is not None:
            params["planned_session_id"] = str(int(planned_session_id))
        if activity_id is not None:
            params["activity_id"] = str(int(activity_id))
        if date:
            params["date"] = date
        return await self._get_json(
            "/api/mcp/me/analysis/session-payload",
            params=params,
        )

    async def preview_plan_import(self, *, import_text: str) -> dict[str, Any]:
        json_payload: dict[str, Any] = {"import_text": import_text}
        if self.settings.training_api_athlete_id is not None:
            json_payload["athlete_id"] = self.settings.training_api_athlete_id
        return await self._post_json(
            "/api/mcp/plan-import/preview",
            json_payload=json_payload,
            token_kind="read",
        )

    async def commit_plan_import(self, *, import_text: str, confirmation: str) -> dict[str, Any]:
        json_payload: dict[str, Any] = {"import_text": import_text, "confirmation": confirmation}
        if self.settings.training_api_athlete_id is not None:
            json_payload["athlete_id"] = self.settings.training_api_athlete_id
        return await self._post_json(
            "/api/mcp/plan-import/commit",
            json_payload=json_payload,
            token_kind="write",
        )

    async def _get_json(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any] | list[dict[str, Any]]:
        base_url, token = self._require_config()
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with self.async_client_factory(
                base_url=base_url,
                headers=headers,
                timeout=20.0,
            ) as client:
                response = await client.get(path, params=params)
        except httpx.RequestError as exc:
            raise ToolError(
                "No se pudo conectar a la API interna de ProyectoGarmin. Verifica que la app principal este disponible."
            ) from exc

        if response.status_code == 401:
            raise ToolError("La API interna rechazo la autenticacion. Revisa TRAINING_APP_MCP_TOKEN.")
        if response.status_code == 404:
            raise ToolError(f"La API interna devolvio 404: {self._extract_error_detail(response)}")
        if response.status_code == 503:
            raise ToolError(f"La API interna no esta lista para MCP: {self._extract_error_detail(response)}")
        if response.status_code >= 500:
            raise ToolError(f"La API interna devolvio {response.status_code}: {self._extract_error_detail(response)}")
        if response.status_code >= 400:
            raise ToolError(f"La API interna devolvio {response.status_code}: {self._extract_error_detail(response)}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ToolError("La API interna respondio con un payload no JSON.") from exc

        if not isinstance(payload, (dict, list)):
            raise ToolError("La API interna respondio con un formato inesperado.")
        return payload

    async def _post_json(
        self,
        path: str,
        *,
        json_payload: dict[str, Any],
        token_kind: str,
    ) -> dict[str, Any]:
        base_url, token = self._require_config(token_kind=token_kind)
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with self.async_client_factory(
                base_url=base_url,
                headers=headers,
                timeout=20.0,
            ) as client:
                response = await client.post(path, json=json_payload)
        except httpx.RequestError as exc:
            raise ToolError(
                "No se pudo conectar a la API interna de ProyectoGarmin. Verifica que la app principal este disponible."
            ) from exc

        if response.status_code == 401:
            token_name = "TRAINING_API_WRITE_TOKEN" if token_kind == "write" else "TRAINING_APP_MCP_TOKEN"
            raise ToolError(f"La API interna rechazo la autenticacion. Revisa {token_name}.")
        if response.status_code == 404:
            raise ToolError(f"La API interna devolvio 404: {self._extract_error_detail(response)}")
        if response.status_code == 503:
            raise ToolError(f"La API interna no esta lista para MCP: {self._extract_error_detail(response)}")
        if response.status_code >= 500:
            raise ToolError(f"La API interna devolvio {response.status_code}: {self._extract_error_detail(response)}")
        if response.status_code >= 400:
            raise ToolError(f"La API interna devolvio {response.status_code}: {self._extract_error_detail(response)}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ToolError("La API interna respondio con un payload no JSON.") from exc
        if not isinstance(payload, dict):
            raise ToolError("La API interna respondio con un formato inesperado.")
        return payload

    def _require_config(self, *, token_kind: str = "read") -> tuple[str, str]:
        base_url = self.settings.training_app_base_url
        token = self.settings.training_api_write_token if token_kind == "write" else self.settings.training_app_mcp_token
        if not base_url:
            raise ToolError("TRAINING_APP_BASE_URL no esta configurado.")
        if not token:
            token_name = "TRAINING_API_WRITE_TOKEN" if token_kind == "write" else "TRAINING_APP_MCP_TOKEN"
            raise ToolError(f"{token_name} no esta configurado.")
        return base_url, token

    @staticmethod
    def _extract_error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            return text or f"HTTP {response.status_code}"

        if isinstance(payload, dict):
            for key in ("detail", "message", "error"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return f"HTTP {response.status_code}"
