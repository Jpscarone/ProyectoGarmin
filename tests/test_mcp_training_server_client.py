from __future__ import annotations

import importlib.util
import inspect
import unittest

import httpx

MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None

if MCP_AVAILABLE:
    from mcp.server.fastmcp.exceptions import ToolError
    from mcp_training_server.client import TrainingAppApiClient
    from mcp_training_server.settings import Settings


@unittest.skipUnless(MCP_AVAILABLE, "mcp SDK no instalado en este entorno de tests")
class TrainingAppApiClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_athletes_returns_json_payload(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/athletes")
            self.assertEqual(request.headers.get("Authorization"), "Bearer token-123")
            return httpx.Response(200, json=[{"id": 1, "name": "Pablo", "status": "active"}])

        client = _build_client(handler)
        payload = await client.get_athletes()

        self.assertIsInstance(payload, list)
        self.assertEqual(payload[0]["name"], "Pablo")

    async def test_get_training_status_maps_401_to_clear_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "Unauthorized"})

        client = _build_client(handler)
        with self.assertRaises(ToolError) as ctx:
            await client.get_training_status(athlete_id=1)

        self.assertIn("TRAINING_APP_MCP_TOKEN", str(ctx.exception))

    async def test_compare_planned_vs_done_passes_optional_query_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/compare/planned-vs-done")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("date"), "2026-05-13")
            self.assertEqual(request.url.params.get("activity_id"), "22")
            self.assertEqual(request.url.params.get("planned_session_id"), "33")
            return httpx.Response(200, json={"date": "2026-05-13", "match": {"source": "none"}})

        client = _build_client(handler)
        payload = await client.compare_planned_vs_done(
            athlete_id=1,
            date="2026-05-13",
            activity_id=22,
            planned_session_id=33,
        )

        self.assertEqual(payload["date"], "2026-05-13")

    async def test_get_next_session_recommendation_passes_optional_query_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training/next-session-recommendation")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-13")
            self.assertEqual(request.url.params.get("planned_session_id"), "44")
            return httpx.Response(200, json={"reference_date": "2026-05-13", "recommendation": {"decision": "keep"}})

        client = _build_client(handler)
        payload = await client.get_next_session_recommendation(
            athlete_id=1,
            reference_date="2026-05-13",
            planned_session_id=44,
        )

        self.assertEqual(payload["recommendation"]["decision"], "keep")

    async def test_get_week_load_summary_passes_optional_query_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training/week-load-summary")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("week_start_date"), "2026-05-11")
            self.assertEqual(request.url.params.get("compare_previous"), "false")
            return httpx.Response(200, json={"week": {"start_date": "2026-05-11"}, "recommendation": {"status": "balanced"}})

        client = _build_client(handler)
        payload = await client.get_week_load_summary(
            athlete_id=1,
            week_start_date="2026-05-11",
            compare_previous=False,
        )

        self.assertEqual(payload["recommendation"]["status"], "balanced")

    async def test_get_remaining_week_plan_passes_optional_query_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training/remaining-week-plan")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("week_start_date"), "2026-05-25")
            return httpx.Response(200, json={"week_start_date": "2026-05-25", "remaining_sessions": 2})

        client = _build_client(handler)
        payload = await client.get_remaining_week_plan(
            athlete_id=1,
            week_start_date="2026-05-25",
        )

        self.assertEqual(payload["remaining_sessions"], 2)

    async def test_get_previous_week_summary_sends_athlete_id(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training/previous-week-summary")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            return httpx.Response(200, json={"week_start_date": "2026-05-18", "total_sessions": 3})

        client = _build_client(handler)
        payload = await client.get_previous_week_summary(athlete_id=1)

        self.assertEqual(payload["total_sessions"], 3)

    async def test_get_next_planned_session_passes_optional_reference_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training/next-planned-session")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-25")
            return httpx.Response(200, json={"date": "2026-05-26", "name": "Series"})

        client = _build_client(handler)
        payload = await client.get_next_planned_session(
            athlete_id=1,
            reference_date="2026-05-25",
        )

        self.assertEqual(payload["name"], "Series")

    async def test_get_today_remaining_sessions_sends_athlete_id(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training/today-remaining-sessions")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            return httpx.Response(200, json={"date": "2026-05-25", "remaining_count": 1})

        client = _build_client(handler)
        payload = await client.get_today_remaining_sessions(athlete_id=1)

        self.assertEqual(payload["remaining_count"], 1)

    async def test_get_week_adherence_passes_optional_query_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training/week-adherence")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("week_start_date"), "2026-05-18")
            return httpx.Response(200, json={"week_start_date": "2026-05-18", "adherence_percent": 80.0})

        client = _build_client(handler)
        payload = await client.get_week_adherence(
            athlete_id=1,
            week_start_date="2026-05-18",
        )

        self.assertEqual(payload["adherence_percent"], 80.0)

    async def test_get_today_coach_briefing_passes_optional_reference_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/today-coach-briefing")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-25")
            return httpx.Response(200, json={"date": "2026-05-25", "decision": {"overall": "green"}})

        client = _build_client(handler)
        payload = await client.get_today_coach_briefing(athlete_id=1, reference_date="2026-05-25")

        self.assertEqual(payload["decision"]["overall"], "green")

    async def test_get_week_comparison_passes_optional_query_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/week-comparison")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("week_start_date"), "2026-05-25")
            return httpx.Response(200, json={"current_week_start_date": "2026-05-25", "delta": {"sessions": 1}})

        client = _build_client(handler)
        payload = await client.get_week_comparison(athlete_id=1, week_start_date="2026-05-25")

        self.assertEqual(payload["delta"]["sessions"], 1)

    async def test_get_training_load_trend_passes_weeks(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training-load-trend")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("weeks"), "5")
            return httpx.Response(200, json={"weeks": 5, "trend_direction": "up"})

        client = _build_client(handler)
        payload = await client.get_training_load_trend(athlete_id=1, weeks=5)

        self.assertEqual(payload["trend_direction"], "up")

    async def test_get_fatigue_risk_summary_passes_optional_reference_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/fatigue-risk-summary")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-25")
            return httpx.Response(200, json={"reference_date": "2026-05-25", "risk_level": "moderate"})

        client = _build_client(handler)
        payload = await client.get_fatigue_risk_summary(athlete_id=1, reference_date="2026-05-25")

        self.assertEqual(payload["risk_level"], "moderate")

    async def test_get_week_strategy_summary_passes_optional_query_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/week-strategy-summary")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("week_start_date"), "2026-05-25")
            return httpx.Response(200, json={"week_start_date": "2026-05-25", "strategy_label": "build"})

        client = _build_client(handler)
        payload = await client.get_week_strategy_summary(athlete_id=1, week_start_date="2026-05-25")

        self.assertEqual(payload["strategy_label"], "build")

    async def test_get_training_dashboard_passes_optional_reference_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training-dashboard")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-25")
            return httpx.Response(200, json={"reference_date": "2026-05-25", "recommended_focus": "Bajar carga"})

        client = _build_client(handler)
        payload = await client.get_training_dashboard(athlete_id=1, reference_date="2026-05-25")

        self.assertEqual(payload["recommended_focus"], "Bajar carga")

    async def test_get_plan_adjustment_suggestions_passes_optional_reference_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/plan-adjustment-suggestions")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-25")
            return httpx.Response(200, json={"risk_level": "moderate", "suggestions": []})

        client = _build_client(handler)
        payload = await client.get_plan_adjustment_suggestions(athlete_id=1, reference_date="2026-05-25")

        self.assertEqual(payload["risk_level"], "moderate")

    async def test_get_next_session_decision_passes_optional_query_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/next-session-decision")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-25")
            self.assertEqual(request.url.params.get("planned_session_id"), "44")
            return httpx.Response(200, json={"decision": "reduce"})

        client = _build_client(handler)
        payload = await client.get_next_session_decision(athlete_id=1, reference_date="2026-05-25", planned_session_id=44)

        self.assertEqual(payload["decision"], "reduce")

    async def test_get_optional_session_impact_passes_target_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/optional-session-impact")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("planned_session_id"), "55")
            self.assertEqual(request.url.params.get("date"), "2026-05-27")
            self.assertEqual(request.url.params.get("sport"), "cycling")
            return httpx.Response(200, json={"impact_level": "low"})

        client = _build_client(handler)
        payload = await client.get_optional_session_impact(
            athlete_id=1,
            planned_session_id=55,
            date="2026-05-27",
            sport="cycling",
        )

        self.assertEqual(payload["impact_level"], "low")

    async def test_generate_plan_adjustment_import_text_passes_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/generate-plan-adjustment-import-text")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("adjustment_type"), "cancel_optional")
            self.assertEqual(request.url.params.get("planned_session_id"), "66")
            self.assertEqual(request.url.params.get("reason"), "fatiga")
            return httpx.Response(200, json={"generated": True, "requires_preview": True})

        client = _build_client(handler)
        payload = await client.generate_plan_adjustment_import_text(
            athlete_id=1,
            adjustment_type="cancel_optional",
            planned_session_id=66,
            reason="fatiga",
        )

        self.assertTrue(payload["generated"])

    async def test_get_training_decision_context_passes_optional_reference_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training-decision-context")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-25")
            return httpx.Response(200, json={"reference_date": "2026-05-25", "summary": "ok"})

        client = _build_client(handler)
        payload = await client.get_training_decision_context(athlete_id=1, reference_date="2026-05-25")

        self.assertEqual(payload["summary"], "ok")

    async def test_get_session_analysis_payload_passes_optional_query_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/analysis/session-payload")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("planned_session_id"), "12")
            self.assertEqual(request.url.params.get("activity_id"), "34")
            self.assertEqual(request.url.params.get("date"), "2026-05-13")
            return httpx.Response(200, json={"resolved_by": "planned_session_id", "data_quality": {"has_metrics_json": False}})

        client = _build_client(handler)
        payload = await client.get_session_analysis_payload(
            athlete_id=1,
            planned_session_id=12,
            activity_id=34,
            date="2026-05-13",
        )

        self.assertEqual(payload["resolved_by"], "planned_session_id")

    async def test_identify_me_uses_access_code_without_athlete_id(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/identify")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"athlete": {"id": 2, "name": "Carolina", "status": "active"}})

        client = _build_client(handler)
        payload = await client.identify_me(access_code="CARO-7K92-XP31")

        self.assertEqual(payload["athlete"]["name"], "Carolina")

    async def test_get_day_overview_sends_athlete_id_and_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training/day-overview")
            self.assertEqual(request.url.params.get("athlete_id"), "2")
            self.assertEqual(request.url.params.get("date"), "2026-05-19")
            return httpx.Response(200, json={"date": "2026-05-19", "planned_sessions": [{"name": "Gimnasio suave"}]})

        client = _build_client(handler)
        payload = await client.get_day_overview(athlete_id=2, date="2026-05-19")

        self.assertEqual(payload["date"], "2026-05-19")
        self.assertEqual(payload["planned_sessions"][0]["name"], "Gimnasio suave")

    async def test_get_day_plan_sends_athlete_id_and_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training/day-plan")
            self.assertEqual(request.url.params.get("athlete_id"), "2")
            self.assertEqual(request.url.params.get("date"), "2026-05-20")
            return httpx.Response(200, json={"date": "2026-05-20", "planned_sessions": [{"name": "Series"}]})

        client = _build_client(handler)
        payload = await client.get_day_plan(athlete_id=2, date="2026-05-20")

        self.assertEqual(payload["planned_sessions"][0]["name"], "Series")

    async def test_get_week_plan_sends_optional_query_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training/week-plan")
            self.assertEqual(request.url.params.get("athlete_id"), "2")
            self.assertEqual(request.url.params.get("week_start_date"), "2026-05-18")
            self.assertEqual(request.url.params.get("include_completed"), "false")
            return httpx.Response(200, json={"week": {"start_date": "2026-05-18"}, "days": []})

        client = _build_client(handler)
        payload = await client.get_week_plan(
            athlete_id=2,
            week_start_date="2026-05-18",
            include_completed=False,
        )

        self.assertEqual(payload["week"]["start_date"], "2026-05-18")

    async def test_get_my_day_overview_only_sends_access_code_and_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/day-overview")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("date"), "19-05-2026")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(
                200,
                json={
                    "date": "2026-05-19",
                    "summary": {"message": "Hay una sesion programada pero no hay actividad Garmin realizada asociada."},
                },
            )

        client = _build_client(handler)
        payload = await client.get_my_day_overview(access_code="CARO-7K92-XP31", date="19-05-2026")

        self.assertEqual(payload["date"], "2026-05-19")

    async def test_get_my_day_plan_only_sends_access_code_and_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/day-plan")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("date"), "20-05-2026")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"date": "2026-05-20", "summary": {"has_sessions": False}})

        client = _build_client(handler)
        payload = await client.get_my_day_plan(access_code="CARO-7K92-XP31", date="20-05-2026")

        self.assertEqual(payload["date"], "2026-05-20")

    async def test_get_my_week_plan_only_sends_access_code_and_filters(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/week-plan")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("week_start_date"), "2026-05-18")
            self.assertEqual(request.url.params.get("include_completed"), "true")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"week": {"start_date": "2026-05-18"}, "days": []})

        client = _build_client(handler)
        payload = await client.get_my_week_plan(
            access_code="CARO-7K92-XP31",
            week_start_date="2026-05-18",
            include_completed=True,
        )

        self.assertEqual(payload["week"]["start_date"], "2026-05-18")

    async def test_get_my_recent_activities_does_not_send_athlete_id(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/activities/recent")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("limit"), "7")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"count": 1, "activities": [{"activity_name": "Rodaje"}]})

        client = _build_client(handler)
        payload = await client.get_my_recent_activities(access_code="CARO-7K92-XP31", limit=7)

        self.assertEqual(payload["count"], 1)

    async def test_get_my_week_load_summary_does_not_send_athlete_id(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/training/week-load-summary")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("week_start_date"), "2026-05-12")
            self.assertEqual(request.url.params.get("compare_previous"), "true")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"week": {"start_date": "2026-05-12"}})

        client = _build_client(handler)
        payload = await client.get_my_week_load_summary(
            access_code="CARO-7K92-XP31",
            week_start_date="2026-05-12",
            compare_previous=True,
        )

        self.assertEqual(payload["week"]["start_date"], "2026-05-12")

    async def test_get_my_remaining_week_plan_does_not_send_athlete_id(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/training/remaining-week-plan")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("week_start_date"), "2026-05-25")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"week_start_date": "2026-05-25", "remaining_sessions": 1})

        client = _build_client(handler)
        payload = await client.get_my_remaining_week_plan(
            access_code="CARO-7K92-XP31",
            week_start_date="2026-05-25",
        )

        self.assertEqual(payload["remaining_sessions"], 1)

    async def test_get_my_previous_week_summary_does_not_send_athlete_id(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/training/previous-week-summary")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"week_start_date": "2026-05-18", "total_sessions": 2})

        client = _build_client(handler)
        payload = await client.get_my_previous_week_summary(access_code="CARO-7K92-XP31")

        self.assertEqual(payload["total_sessions"], 2)

    async def test_get_my_next_planned_session_only_sends_access_code_and_reference_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/training/next-planned-session")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-25")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"date": "2026-05-26", "name": "Tempo"})

        client = _build_client(handler)
        payload = await client.get_my_next_planned_session(
            access_code="CARO-7K92-XP31",
            reference_date="2026-05-25",
        )

        self.assertEqual(payload["name"], "Tempo")

    async def test_get_my_today_remaining_sessions_only_sends_access_code(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/training/today-remaining-sessions")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"date": "2026-05-25", "remaining_count": 2})

        client = _build_client(handler)
        payload = await client.get_my_today_remaining_sessions(access_code="CARO-7K92-XP31")

        self.assertEqual(payload["remaining_count"], 2)

    async def test_get_my_week_adherence_only_sends_access_code_and_week_start_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/training/week-adherence")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("week_start_date"), "2026-05-18")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"week_start_date": "2026-05-18", "adherence_percent": 75.0})

        client = _build_client(handler)
        payload = await client.get_my_week_adherence(
            access_code="CARO-7K92-XP31",
            week_start_date="2026-05-18",
        )

        self.assertEqual(payload["adherence_percent"], 75.0)

    async def test_get_my_today_coach_briefing_only_sends_access_code_and_reference_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/my/today-coach-briefing")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-25")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"date": "2026-05-25", "decision": {"overall": "yellow"}})

        client = _build_client(handler)
        payload = await client.get_my_today_coach_briefing(access_code="CARO-7K92-XP31", reference_date="2026-05-25")

        self.assertEqual(payload["decision"]["overall"], "yellow")

    async def test_get_my_week_comparison_only_sends_access_code_and_week_start_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/week-comparison")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("week_start_date"), "2026-05-25")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"current_week_start_date": "2026-05-25", "delta": {"sessions": -1}})

        client = _build_client(handler)
        payload = await client.get_my_week_comparison(access_code="CARO-7K92-XP31", week_start_date="2026-05-25")

        self.assertEqual(payload["delta"]["sessions"], -1)

    async def test_get_my_training_load_trend_only_sends_access_code_and_weeks(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/training-load-trend")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("weeks"), "6")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"weeks": 6, "trend_direction": "mixed"})

        client = _build_client(handler)
        payload = await client.get_my_training_load_trend(access_code="CARO-7K92-XP31", weeks=6)

        self.assertEqual(payload["trend_direction"], "mixed")

    async def test_get_my_fatigue_risk_summary_only_sends_access_code_and_reference_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/fatigue-risk-summary")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-25")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"reference_date": "2026-05-25", "risk_level": "high"})

        client = _build_client(handler)
        payload = await client.get_my_fatigue_risk_summary(access_code="CARO-7K92-XP31", reference_date="2026-05-25")

        self.assertEqual(payload["risk_level"], "high")

    async def test_get_my_week_strategy_summary_only_sends_access_code_and_week_start_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/week-strategy-summary")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("week_start_date"), "2026-05-25")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"week_start_date": "2026-05-25", "strategy_label": "specific"})

        client = _build_client(handler)
        payload = await client.get_my_week_strategy_summary(access_code="CARO-7K92-XP31", week_start_date="2026-05-25")

        self.assertEqual(payload["strategy_label"], "specific")

    async def test_get_my_training_dashboard_only_sends_access_code_and_reference_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/training-dashboard")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-25")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"reference_date": "2026-05-25", "key_message": "Todo estable"})

        client = _build_client(handler)
        payload = await client.get_my_training_dashboard(access_code="CARO-7K92-XP31", reference_date="2026-05-25")

        self.assertEqual(payload["key_message"], "Todo estable")

    async def test_get_my_plan_adjustment_suggestions_only_sends_access_code_and_reference_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/plan-adjustment-suggestions")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-25")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"risk_level": "high"})

        client = _build_client(handler)
        payload = await client.get_my_plan_adjustment_suggestions(access_code="CARO-7K92-XP31", reference_date="2026-05-25")

        self.assertEqual(payload["risk_level"], "high")

    async def test_get_my_next_session_decision_only_sends_access_code_and_target(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/next-session-decision")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-25")
            self.assertEqual(request.url.params.get("planned_session_id"), "44")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"decision": "cancel_optional"})

        client = _build_client(handler)
        payload = await client.get_my_next_session_decision(
            access_code="CARO-7K92-XP31",
            reference_date="2026-05-25",
            planned_session_id=44,
        )

        self.assertEqual(payload["decision"], "cancel_optional")

    async def test_get_my_optional_session_impact_only_sends_access_code_and_target(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/optional-session-impact")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("planned_session_id"), "55")
            self.assertEqual(request.url.params.get("date"), "2026-05-27")
            self.assertEqual(request.url.params.get("sport"), "cycling")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"impact_level": "moderate"})

        client = _build_client(handler)
        payload = await client.get_my_optional_session_impact(
            access_code="CARO-7K92-XP31",
            planned_session_id=55,
            date="2026-05-27",
            sport="cycling",
        )

        self.assertEqual(payload["impact_level"], "moderate")

    async def test_get_my_plan_adjustment_import_text_only_sends_access_code_and_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/generate-plan-adjustment-import-text")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("adjustment_type"), "reduce_next")
            self.assertEqual(request.url.params.get("planned_session_id"), "66")
            self.assertEqual(request.url.params.get("reason"), "fatiga")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"generated": False})

        client = _build_client(handler)
        payload = await client.get_my_plan_adjustment_import_text(
            access_code="CARO-7K92-XP31",
            adjustment_type="reduce_next",
            planned_session_id=66,
            reason="fatiga",
        )

        self.assertFalse(payload["generated"])

    async def test_get_my_training_decision_context_only_sends_access_code_and_reference_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/training-decision-context")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-25")
            self.assertIsNone(request.url.params.get("athlete_id"))
            return httpx.Response(200, json={"summary": "decision context"})

        client = _build_client(handler)
        payload = await client.get_my_training_decision_context(access_code="CARO-7K92-XP31", reference_date="2026-05-25")

        self.assertEqual(payload["summary"], "decision context")

    async def test_preview_plan_import_posts_with_read_token(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/plan-import/preview")
            self.assertEqual(request.headers.get("Authorization"), "Bearer token-123")
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.read().decode(), '{"import_text":"SESSION\\nEND"}')
            return httpx.Response(200, json={"valid": True, "operations": []})

        client = _build_client(handler)
        payload = await client.preview_plan_import(import_text="SESSION\nEND")

        self.assertTrue(payload["valid"])

    async def test_verify_plan_import_posts_with_read_token(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/plan-import/verify")
            self.assertEqual(request.headers.get("Authorization"), "Bearer token-123")
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.read().decode(), '{"import_text":"SESSION\\nEND"}')
            return httpx.Response(200, json={"valid": True, "matched_sessions": 1})

        client = _build_client(handler)
        payload = await client.verify_plan_import(import_text="SESSION\nEND")

        self.assertTrue(payload["valid"])

    async def test_commit_plan_import_posts_with_write_token(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/plan-import/commit")
            self.assertEqual(request.headers.get("Authorization"), "Bearer write-token-123")
            self.assertEqual(request.method, "POST")
            return httpx.Response(200, json={"created": 1, "affected_session_ids": [10]})

        client = _build_client(handler)
        payload = await client.commit_plan_import(import_text="SESSION\nEND", confirmation="APLICAR")

        self.assertEqual(payload["created"], 1)

    async def test_training_api_athlete_id_is_sent_only_as_fallback(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/plan-import/preview")
            self.assertEqual(request.headers.get("Authorization"), "Bearer token-123")
            self.assertEqual(request.read().decode(), '{"import_text":"WEEK\\nATHLETE_ID: 2\\nEND","athlete_id":1}')
            return httpx.Response(200, json={"athlete": {"id": 2}, "valid": True, "operations": []})

        client = _build_client(handler, training_api_athlete_id=1)
        payload = await client.preview_plan_import(import_text="WEEK\nATHLETE_ID: 2\nEND")

        self.assertEqual(payload["athlete"]["id"], 2)

    async def test_compare_my_planned_vs_done_only_sends_access_code_and_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/compare/planned-vs-done")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("date"), "2026-05-18")
            self.assertIsNone(request.url.params.get("athlete_id"))
            self.assertIsNone(request.url.params.get("activity_id"))
            self.assertIsNone(request.url.params.get("planned_session_id"))
            return httpx.Response(200, json={"date": "2026-05-18"})

        client = _build_client(handler)
        payload = await client.compare_my_planned_vs_done(
            access_code="CARO-7K92-XP31",
            date="2026-05-18",
        )

        self.assertEqual(payload["date"], "2026-05-18")

    async def test_get_my_next_session_recommendation_only_sends_access_code_and_reference_date(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/me/training/next-session-recommendation")
            self.assertEqual(request.url.params.get("access_code"), "CARO-7K92-XP31")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-18")
            self.assertIsNone(request.url.params.get("athlete_id"))
            self.assertIsNone(request.url.params.get("planned_session_id"))
            return httpx.Response(200, json={"reference_date": "2026-05-18"})

        client = _build_client(handler)
        payload = await client.get_my_next_session_recommendation(
            access_code="CARO-7K92-XP31",
            reference_date="2026-05-18",
        )

        self.assertEqual(payload["reference_date"], "2026-05-18")

    def test_my_tool_signatures_do_not_accept_athlete_id(self) -> None:
        from mcp_training_server import server as mcp_server

        signatures = {
            "identify_me": inspect.signature(mcp_server.identify_me),
            "get_my_day_plan": inspect.signature(mcp_server.get_my_day_plan),
            "get_my_day_overview": inspect.signature(mcp_server.get_my_day_overview),
            "get_my_recent_activities": inspect.signature(mcp_server.get_my_recent_activities),
            "get_my_health_summary": inspect.signature(mcp_server.get_my_health_summary),
            "get_my_training_status": inspect.signature(mcp_server.get_my_training_status),
            "get_my_week_plan": inspect.signature(mcp_server.get_my_week_plan),
            "compare_my_planned_vs_done": inspect.signature(mcp_server.compare_my_planned_vs_done),
            "get_my_next_session_recommendation": inspect.signature(mcp_server.get_my_next_session_recommendation),
            "get_my_week_load_summary": inspect.signature(mcp_server.get_my_week_load_summary),
            "get_my_remaining_week_plan": inspect.signature(mcp_server.get_my_remaining_week_plan),
            "get_my_previous_week_summary": inspect.signature(mcp_server.get_my_previous_week_summary),
            "get_my_next_planned_session": inspect.signature(mcp_server.get_my_next_planned_session),
            "get_my_today_remaining_sessions": inspect.signature(mcp_server.get_my_today_remaining_sessions),
            "get_my_week_adherence": inspect.signature(mcp_server.get_my_week_adherence),
            "get_my_week_comparison": inspect.signature(mcp_server.get_my_week_comparison),
            "get_my_training_load_trend": inspect.signature(mcp_server.get_my_training_load_trend),
            "get_my_fatigue_risk_summary": inspect.signature(mcp_server.get_my_fatigue_risk_summary),
            "get_my_week_strategy_summary": inspect.signature(mcp_server.get_my_week_strategy_summary),
            "get_my_training_dashboard": inspect.signature(mcp_server.get_my_training_dashboard),
            "get_my_plan_adjustment_suggestions": inspect.signature(mcp_server.get_my_plan_adjustment_suggestions),
            "get_my_next_session_decision": inspect.signature(mcp_server.get_my_next_session_decision),
            "get_my_optional_session_impact": inspect.signature(mcp_server.get_my_optional_session_impact),
            "get_my_plan_adjustment_import_text": inspect.signature(mcp_server.get_my_plan_adjustment_import_text),
            "get_my_training_decision_context": inspect.signature(mcp_server.get_my_training_decision_context),
            "get_my_session_analysis_payload": inspect.signature(mcp_server.get_my_session_analysis_payload),
        }

        for tool_name, signature in signatures.items():
            self.assertNotIn("athlete_id", signature.parameters, tool_name)


def _build_client(handler, *, training_api_athlete_id: int | None = None) -> TrainingAppApiClient:
    settings = Settings(
        training_app_base_url="http://testserver",
        training_app_mcp_token="token-123",
        training_api_write_token="write-token-123",
        training_api_athlete_id=training_api_athlete_id,
        mcp_transport="http",
        mcp_host="127.0.0.1",
        mcp_port=9000,
        mcp_http_path="/mcp",
        mcp_sse_path="/sse",
        mcp_message_path="/messages/",
    )

    class TestAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    return TrainingAppApiClient(settings, async_client_factory=TestAsyncClient)
