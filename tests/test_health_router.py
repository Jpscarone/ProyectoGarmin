from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models import daily_health_metric  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import health_ai_analysis  # noqa: F401
from app.db.models import health_sync_state  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.garmin_activity import GarminActivity
from app.db.session import get_db
from app.main import app
from app.schemas.daily_health_metric import HealthDailyMetricCreate
from app.services.daily_health_metric_service import create_or_update_daily_health_metric
from app.services.health_ai_analysis_service import (
    create_health_ai_analysis,
    get_latest_health_ai_analysis_for_date,
    list_health_ai_analyses_for_athlete,
)
from app.services.openai_client import OpenAIIntegrationError
from app.db.models.health_sync_state import HealthSyncState


class HealthRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        athlete_row = Athlete(name="Atleta Router Salud")
        self.db.add(athlete_row)
        self.db.commit()
        self.db.refresh(athlete_row)
        self.athlete = athlete_row

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def test_health_readiness_endpoint_returns_summary_and_evaluation(self) -> None:
        reference_date = date(2026, 4, 23)
        for offset in range(14):
            metric_date = reference_date - timedelta(days=offset)
            create_or_update_daily_health_metric(
                self.db,
                HealthDailyMetricCreate(
                    athlete_id=self.athlete.id,
                    date=metric_date,
                    sleep_duration_minutes=470,
                    sleep_score=82,
                    resting_hr=49,
                    hrv_value=61.0,
                    hrv_status="stable",
                    stress_avg=24,
                    body_battery_morning=73,
                    body_battery_min=32,
                    body_battery_max=81,
                    training_load=290.0,
                    source="garmin",
                ),
            )

        response = self.client.get(
            f"/health/readiness?athlete_id={self.athlete.id}&selected_date={reference_date.isoformat()}"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["athlete_id"], self.athlete.id)
        self.assertIn("summary", payload)
        self.assertIn("evaluation", payload)
        self.assertEqual(payload["evaluation"]["readiness_status"], "green")
        self.assertEqual(payload["summary"]["available_days_14d"], 14)

    def test_health_html_renders_with_insufficient_data(self) -> None:
        response = self.client.get("/health", headers={"accept": "text/html"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Estado para entrenar el", response.text)
        self.assertIn("sin datos suficientes", response.text.lower())
        self.assertIn("Contexto de entrenamiento reciente", response.text)
        self.assertIn("Sin datos recientes de entrenamiento.", response.text)

    def test_health_html_uses_selected_date(self) -> None:
        response = self.client.get(
            "/health?selected_date=2026-04-18",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Estado para entrenar el 18/04/2026", response.text)

    def test_health_html_renders_quick_navigation_links(self) -> None:
        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date=2026-04-18",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("selected_date=2026-04-17", response.text)
        self.assertIn("selected_date=2026-04-11", response.text)
        self.assertIn("selected_date=2026-04-19", response.text)
        self.assertIn("Ayer", response.text)
        self.assertIn("-7 dias", response.text)
        self.assertIn("+1 dia", response.text)
        self.assertIn("Hoy", response.text)

    def test_health_html_renders_copy_json_button_with_correct_url(self) -> None:
        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date=2026-04-18",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Copiar JSON para IA", response.text)
        self.assertIn(
            'data-health-llm-copy-url="/health/readiness/llm-json?selected_date=2026-04-18&amp;athlete_id=1"',
            response.text,
        )

    def test_health_html_renders_ai_analysis_button_with_correct_url(self) -> None:
        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date=2026-04-18",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Analizar con IA", response.text)
        self.assertIn(
            'data-health-ai-analysis-url="/health/readiness/ai-analysis?selected_date=2026-04-18&amp;athlete_id=1"',
            response.text,
        )
        self.assertIn("Copiar analisis IA", response.text)
        self.assertIn("copyHealthAiAnalysis(this)", response.text)

    def test_health_html_auto_sync_success_triggers_auto_ai_analysis(self) -> None:
        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date=2026-04-18",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("data-health-auto-ai-analysis-url=", response.text)
        self.assertIn("if (payload.synced) {", response.text)
        self.assertIn("runHealthAutoAiAnalysisAfterSync(statusEl)", response.text)

    def test_health_html_auto_sync_fresh_does_not_trigger_auto_ai_analysis(self) -> None:
        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date=2026-04-18",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        fresh_message_index = response.text.index("Salud ya sincronizada recientemente")
        auto_ai_call_index = response.text.index("runHealthAutoAiAnalysisAfterSync(statusEl)")
        self.assertLess(auto_ai_call_index, fresh_message_index)

    def test_health_html_copy_json_button_updates_when_selected_date_changes(self) -> None:
        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date=2026-04-12",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'data-health-llm-copy-url="/health/readiness/llm-json?selected_date=2026-04-12&amp;athlete_id=1"',
            response.text,
        )

    def test_health_html_ai_analysis_button_updates_when_selected_date_changes(self) -> None:
        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date=2026-04-12",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'data-health-ai-analysis-url="/health/readiness/ai-analysis?selected_date=2026-04-12&amp;athlete_id=1"',
            response.text,
        )
        self.assertIn("buildHealthAiAnalysisText", response.text)
        self.assertIn("Array.isArray(safeAnalysis.main_factors)", response.text)
        self.assertIn("Array.isArray(safeAnalysis.what_to_watch)", response.text)

    def test_health_html_hides_plus_one_day_when_selected_date_is_today(self) -> None:
        today = date.today().isoformat()
        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date={today}",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(">+1 dia<", response.text)

    def test_health_readiness_endpoint_uses_selected_date(self) -> None:
        response = self.client.get(
            f"/health/readiness?athlete_id={self.athlete.id}&selected_date=2026-04-18"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["selected_date"], "2026-04-18")

    def test_health_readiness_endpoint_invalid_selected_date_is_controlled(self) -> None:
        response = self.client.get(
            f"/health/readiness?athlete_id={self.athlete.id}&selected_date=2026-99-99"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["error"], "invalid_selected_date")
        self.assertIn("readiness", payload)

    def test_health_readiness_llm_json_endpoint_uses_selected_date(self) -> None:
        reference_date = date(2026, 4, 23)
        for offset in range(14):
            metric_date = reference_date - timedelta(days=offset)
            create_or_update_daily_health_metric(
                self.db,
                HealthDailyMetricCreate(
                    athlete_id=self.athlete.id,
                    date=metric_date,
                    sleep_duration_minutes=470,
                    sleep_score=82,
                    resting_hr=49,
                    hrv_value=61.0,
                    hrv_status="stable",
                    stress_avg=24,
                    body_battery_morning=73,
                    body_battery_min=32,
                    body_battery_max=81,
                    training_load=290.0,
                    source="garmin",
                ),
            )

        response = self.client.get(
            f"/health/readiness/llm-json?athlete_id={self.athlete.id}&selected_date=2026-04-18"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "health_readiness_v1")
        self.assertEqual(payload["reference_date"], "2026-04-18")
        self.assertIn("health_summary", payload)
        self.assertIn("readiness_local", payload)

    def test_health_readiness_llm_json_endpoint_includes_training_context(self) -> None:
        self.db.add(
            GarminActivity(
                athlete_id=self.athlete.id,
                garmin_activity_id=5001,
                activity_name="Tempo router",
                sport_type="running",
                start_time=datetime(2026, 4, 17, 8, 0),
                duration_sec=3000,
                distance_m=9000,
                training_effect_aerobic=3.8,
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/health/readiness/llm-json?athlete_id={self.athlete.id}&selected_date=2026-04-18"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("training_context", payload)
        self.assertEqual(payload["training_context"]["completed_activities_last_7d"], 1)
        self.assertEqual(payload["training_context"]["last_activity_date"], "2026-04-17")
        self.assertEqual(payload["training_context"]["hard_sessions_last_7d"], 1)

    def test_health_html_renders_training_context_when_available(self) -> None:
        self.db.add(
            GarminActivity(
                athlete_id=self.athlete.id,
                garmin_activity_id=5002,
                activity_name="Rodaje router",
                sport_type="running",
                start_time=datetime(2026, 4, 17, 8, 0),
                duration_sec=3600,
                distance_m=10000,
                training_effect_aerobic=2.4,
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date=2026-04-18",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Contexto de entrenamiento reciente", response.text)
        self.assertIn("Actividades 7d", response.text)
        self.assertIn("Ultima actividad", response.text)
        self.assertIn("17/04/2026", response.text)
        self.assertIn("Km totales 7d", response.text)

    def test_health_html_training_context_does_not_break_with_null_fields(self) -> None:
        self.db.add(
            GarminActivity(
                athlete_id=self.athlete.id,
                garmin_activity_id=5003,
                activity_name="Actividad parcial",
                sport_type="running",
                start_time=datetime(2026, 4, 17, 8, 0),
                duration_sec=None,
                distance_m=None,
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date=2026-04-18",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Contexto de entrenamiento reciente", response.text)
        self.assertIn("Actividades 7d", response.text)
        self.assertIn("Minutos totales 7d", response.text)
        self.assertIn("Km totales 7d", response.text)

    @patch("app.routers.health.analyze_health_readiness_with_ai")
    def test_health_ai_analysis_endpoint_returns_expected_structure(self, mock_analyze) -> None:
        reference_date = date(2026, 4, 23)
        for offset in range(14):
            metric_date = reference_date - timedelta(days=offset)
            create_or_update_daily_health_metric(
                self.db,
                HealthDailyMetricCreate(
                    athlete_id=self.athlete.id,
                    date=metric_date,
                    sleep_duration_minutes=470,
                    sleep_score=82,
                    resting_hr=49,
                    hrv_value=61.0,
                    hrv_status="stable",
                    stress_avg=24,
                    body_battery_morning=73,
                    body_battery_min=32,
                    body_battery_max=81,
                    training_load=290.0,
                    source="garmin",
                ),
            )

        mock_analyze.return_value = {
            "summary": "Readiness bastante estable para entrenar.",
            "training_recommendation": "Podes sostener lo planificado sin forzar de mas.",
            "risk_level": "low",
            "main_factors": ["Sueno estable", "FC reposo controlada"],
            "what_to_watch": ["Seguir monitoreando la HRV"],
            "not_medical_advice": True,
        }

        response = self.client.post(
            f"/health/readiness/ai-analysis?athlete_id={self.athlete.id}&selected_date=2026-04-18"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["selected_date"], "2026-04-18")
        self.assertIn("analysis", payload)
        self.assertEqual(payload["analysis"]["risk_level"], "low")
        self.assertEqual(payload["analysis"]["not_medical_advice"], True)
        self.assertIn("llm_json", payload)
        self.assertIn("saved_analysis", payload)
        self.assertEqual(payload["saved_analysis"]["risk_level"], "low")
        latest = get_latest_health_ai_analysis_for_date(self.db, self.athlete.id, date(2026, 4, 18))
        self.assertIsNotNone(latest)
        self.assertEqual(latest.summary, "Readiness bastante estable para entrenar.")
        mock_analyze.assert_called_once()

    @patch("app.routers.health.analyze_health_readiness_with_ai")
    def test_health_ai_analysis_endpoint_handles_missing_api_key(self, mock_analyze) -> None:
        mock_analyze.side_effect = OpenAIIntegrationError("OPENAI_API_KEY no configurada.")

        response = self.client.post(
            f"/health/readiness/ai-analysis?athlete_id={self.athlete.id}&selected_date=2026-04-18"
        )

        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertEqual(payload["error"], "missing_api_key")
        self.assertIn("OPENAI_API_KEY", payload["message"])
        self.assertIsNone(get_latest_health_ai_analysis_for_date(self.db, self.athlete.id, date(2026, 4, 18)))

    def test_get_latest_health_ai_analysis_for_date_returns_newest(self) -> None:
        first = create_health_ai_analysis(
            self.db,
            athlete_id=self.athlete.id,
            reference_date=date(2026, 4, 18),
            llm_json={"schema_version": "health_readiness_v1"},
            ai_response_json={"summary": "Primero"},
            summary="Primero",
            training_recommendation="Suave",
            risk_level="moderate",
            model_name="gpt-test",
        )
        second = create_health_ai_analysis(
            self.db,
            athlete_id=self.athlete.id,
            reference_date=date(2026, 4, 18),
            llm_json={"schema_version": "health_readiness_v1"},
            ai_response_json={"summary": "Segundo"},
            summary="Segundo",
            training_recommendation="Normal",
            risk_level="low",
            model_name="gpt-test",
        )

        latest = get_latest_health_ai_analysis_for_date(self.db, self.athlete.id, date(2026, 4, 18))

        self.assertIsNotNone(latest)
        self.assertEqual(latest.id, second.id)
        analyses = list_health_ai_analyses_for_athlete(self.db, self.athlete.id)
        self.assertEqual([row.id for row in analyses], [second.id, first.id])

    def test_health_html_shows_latest_saved_ai_analysis(self) -> None:
        create_health_ai_analysis(
            self.db,
            athlete_id=self.athlete.id,
            reference_date=date(2026, 4, 18),
            llm_json={"schema_version": "health_readiness_v1"},
            ai_response_json={
                "summary": "Readiness estable.",
                "training_recommendation": "Mantener control.",
                "risk_level": "low",
                "main_factors": ["Sueno"],
                "what_to_watch": ["HRV"],
                "not_medical_advice": True,
            },
            summary="Readiness estable.",
            training_recommendation="Mantener control.",
            risk_level="low",
            model_name="gpt-test",
        )

        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date=2026-04-18",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Ultimo analisis IA guardado", response.text)
        self.assertIn("Readiness estable.", response.text)
        self.assertIn("Mantener control.", response.text)
        self.assertIn("Analizar con IA", response.text)

    def test_health_html_shows_recent_ai_history_when_available(self) -> None:
        create_health_ai_analysis(
            self.db,
            athlete_id=self.athlete.id,
            reference_date=date(2026, 4, 18),
            llm_json={
                "schema_version": "health_readiness_v1",
                "readiness_local": {
                    "readiness_status": "green",
                    "readiness_label": "entrenar normal",
                    "readiness_score": 88,
                },
            },
            ai_response_json={
                "summary": "Readiness estable.",
                "training_recommendation": "Mantener control.",
                "risk_level": "low",
                "main_factors": ["Sueno"],
                "what_to_watch": ["HRV"],
                "not_medical_advice": True,
            },
            summary="Readiness estable.",
            training_recommendation="Mantener control.",
            risk_level="low",
            model_name="gpt-test",
        )
        create_health_ai_analysis(
            self.db,
            athlete_id=self.athlete.id,
            reference_date=date(2026, 4, 16),
            llm_json={
                "schema_version": "health_readiness_v1",
                "readiness_local": {
                    "readiness_status": "yellow",
                    "readiness_label": "controlar intensidad",
                    "readiness_score": 72,
                },
            },
            ai_response_json={
                "summary": "Algo de carga acumulada.",
                "training_recommendation": "Evitar forzar.",
                "risk_level": "moderate",
                "main_factors": ["FC reposo"],
                "what_to_watch": ["Stress"],
                "not_medical_advice": True,
            },
            summary="Algo de carga acumulada.",
            training_recommendation="Evitar forzar.",
            risk_level="moderate",
            model_name="gpt-test",
        )

        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date=2026-04-18",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Historial reciente de analisis IA", response.text)
        self.assertIn("Tendencia reciente de readiness", response.text)
        self.assertIn("health-readiness-trend", response.text)
        self.assertIn("Readiness estable.", response.text)
        self.assertIn("Algo de carga acumulada.", response.text)
        self.assertIn("/health?selected_date=2026-04-18&amp;athlete_id=1", response.text)
        self.assertIn("/health?selected_date=2026-04-16&amp;athlete_id=1", response.text)

    def test_health_html_shows_empty_ai_history_message_when_none(self) -> None:
        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date=2026-04-18",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Todavia no hay analisis IA guardados.", response.text)
        self.assertIn("Todavia no hay suficientes analisis guardados para mostrar tendencia.", response.text)

    def test_health_readiness_endpoint_prepares_ai_trend_points(self) -> None:
        create_health_ai_analysis(
            self.db,
            athlete_id=self.athlete.id,
            reference_date=date(2026, 4, 18),
            llm_json={
                "schema_version": "health_readiness_v1",
                "readiness_local": {
                    "readiness_status": "green",
                    "readiness_label": "entrenar normal",
                    "readiness_score": 88,
                },
            },
            ai_response_json={"summary": "Readiness estable.", "risk_level": "low"},
            summary="Readiness estable.",
            training_recommendation="Mantener control.",
            risk_level="low",
            model_name="gpt-test",
        )
        create_health_ai_analysis(
            self.db,
            athlete_id=self.athlete.id,
            reference_date=date(2026, 4, 19),
            llm_json={
                "schema_version": "health_readiness_v1",
                "readiness_local": {
                    "readiness_status": "yellow",
                    "readiness_label": "controlar intensidad",
                    "readiness_score": 74,
                },
            },
            ai_response_json={"summary": "Algo de carga.", "risk_level": "moderate"},
            summary="Algo de carga.",
            training_recommendation="Controlar.",
            risk_level="moderate",
            model_name="gpt-test",
        )

        response = self.client.get(
            f"/health/readiness?athlete_id={self.athlete.id}&selected_date=2026-04-19"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        trend = payload["recent_ai_trend"]
        self.assertTrue(trend["has_enough_points"])
        self.assertEqual(len(trend["points"]), 2)
        self.assertEqual(trend["points"][0]["reference_date"], "2026-04-18")
        self.assertEqual(trend["points"][1]["readiness_score"], 74)

    def test_health_html_shows_insufficient_trend_with_one_point(self) -> None:
        create_health_ai_analysis(
            self.db,
            athlete_id=self.athlete.id,
            reference_date=date(2026, 4, 18),
            llm_json={
                "schema_version": "health_readiness_v1",
                "readiness_local": {
                    "readiness_status": "green",
                    "readiness_label": "entrenar normal",
                    "readiness_score": 88,
                },
            },
            ai_response_json={"summary": "Readiness estable.", "risk_level": "low"},
            summary="Readiness estable.",
            training_recommendation="Mantener control.",
            risk_level="low",
            model_name="gpt-test",
        )

        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date=2026-04-18",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Tendencia reciente de readiness", response.text)
        self.assertIn("Todavia no hay suficientes analisis guardados para mostrar tendencia.", response.text)

    def test_health_html_renders_sync_state(self) -> None:
        self.db.add(
            HealthSyncState(
                athlete_id=self.athlete.id,
                source="garmin",
                status="success",
                last_success_at=datetime(2026, 4, 18, 10, 30),
                last_synced_for_date=date(2026, 4, 18),
                records_created=1,
                records_updated=2,
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/health?athlete_id={self.athlete.id}&selected_date=2026-04-18",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("health-sync-status", response.text)
        self.assertIn("Salud sincronizada", response.text)

    def test_health_auto_sync_returns_fresh_when_recent_success_exists(self) -> None:
        self.db.add(
            HealthSyncState(
                athlete_id=self.athlete.id,
                source="garmin",
                status="success",
                last_success_at=datetime.now(timezone.utc) - timedelta(hours=1),
                last_synced_for_date=date.today(),
            )
        )
        self.db.commit()

        response = self.client.post(
            f"/health/auto-sync?athlete_id={self.athlete.id}&selected_date={date.today().isoformat()}"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["synced"])
        self.assertEqual(payload["reason"], "fresh")

    @patch("app.services.health_auto_sync_service.sync_recent_health")
    def test_health_auto_sync_handles_garmin_error(self, mock_sync) -> None:
        mock_sync.side_effect = RuntimeError("Garmin temporalmente no disponible")

        response = self.client.post(
            f"/health/auto-sync?athlete_id={self.athlete.id}&selected_date={date.today().isoformat()}&force=true"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["synced"])
        self.assertEqual(payload["reason"], "failed")
        self.assertIn("Garmin temporalmente no disponible", payload["error"])

    @patch("app.routers.health.analyze_health_readiness_with_ai")
    def test_auto_ai_analysis_runs_when_no_previous_analysis(self, mock_analyze) -> None:
        mock_analyze.return_value = {
            "summary": "Readiness estable.",
            "training_recommendation": "Entrenar con control.",
            "risk_level": "low",
            "main_factors": ["Buen sueno"],
            "what_to_watch": [],
            "not_medical_advice": True,
        }

        response = self.client.post(
            f"/health/readiness/auto-ai-analysis?athlete_id={self.athlete.id}&selected_date=2026-04-18"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ran"])
        latest = get_latest_health_ai_analysis_for_date(self.db, self.athlete.id, date(2026, 4, 18))
        self.assertIsNotNone(latest)
        self.assertIsNotNone(latest.llm_json_hash)

    @patch("app.services.health_ai_analysis_service.build_openai_client")
    @patch("app.services.health_ai_analysis_service.get_settings")
    def test_health_ai_analysis_serializes_date_values_before_openai(self, mock_settings, mock_client_builder) -> None:
        from types import SimpleNamespace
        from app.services.health_ai_analysis_service import analyze_health_readiness_with_ai

        mock_settings.return_value = SimpleNamespace(
            openai_api_key="test-key",
            openai_model="gpt-test",
            openai_timeout_sec=10,
            openai_max_output_tokens_session=700,
        )
        parsed = {
            "summary": "Ok",
            "training_recommendation": "Ok",
            "risk_level": "low",
            "main_factors": [],
            "what_to_watch": [],
            "not_medical_advice": True,
        }
        mock_client_builder.return_value.responses.parse.return_value = SimpleNamespace(output_parsed=parsed)

        result = analyze_health_readiness_with_ai({"reference_date": date(2026, 4, 29)})

        self.assertEqual(result["risk_level"], "low")
        call_kwargs = mock_client_builder.return_value.responses.parse.call_args.kwargs
        self.assertIn("2026-04-29", call_kwargs["input"])

    @patch("app.routers.health.analyze_health_readiness_with_ai")
    def test_auto_ai_analysis_skips_when_hash_matches(self, mock_analyze) -> None:
        readiness = self.client.get(
            f"/health/readiness/llm-json?athlete_id={self.athlete.id}&selected_date=2026-04-18"
        ).json()
        from app.services.health_ai_analysis_service import build_health_llm_json_hash

        create_health_ai_analysis(
            self.db,
            athlete_id=self.athlete.id,
            reference_date=date(2026, 4, 18),
            llm_json=readiness,
            llm_json_hash=build_health_llm_json_hash(readiness),
            ai_response_json={"summary": "Ya guardado.", "risk_level": "low"},
            summary="Ya guardado.",
            training_recommendation="Mantener.",
            risk_level="low",
            model_name="gpt-test",
        )

        response = self.client.post(
            f"/health/readiness/auto-ai-analysis?athlete_id={self.athlete.id}&selected_date=2026-04-18"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ran"])
        self.assertEqual(payload["reason"], "already_analyzed")
        mock_analyze.assert_not_called()

    @patch("app.routers.health.analyze_health_readiness_with_ai")
    def test_auto_ai_analysis_runs_when_json_changes(self, mock_analyze) -> None:
        create_health_ai_analysis(
            self.db,
            athlete_id=self.athlete.id,
            reference_date=date(2026, 4, 18),
            llm_json={"old": True},
            llm_json_hash="old-hash",
            ai_response_json={"summary": "Viejo.", "risk_level": "low"},
            summary="Viejo.",
            training_recommendation="Mantener.",
            risk_level="low",
            model_name="gpt-test",
        )
        mock_analyze.return_value = {
            "summary": "Nuevo.",
            "training_recommendation": "Ajustar.",
            "risk_level": "moderate",
            "main_factors": [],
            "what_to_watch": [],
            "not_medical_advice": True,
        }

        response = self.client.post(
            f"/health/readiness/auto-ai-analysis?athlete_id={self.athlete.id}&selected_date=2026-04-18"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ran"])
        mock_analyze.assert_called_once()

    @patch("app.routers.health.analyze_health_readiness_with_ai")
    def test_auto_ai_analysis_error_does_not_save_analysis(self, mock_analyze) -> None:
        mock_analyze.side_effect = OpenAIIntegrationError("OpenAI fallo")

        response = self.client.post(
            f"/health/readiness/auto-ai-analysis?athlete_id={self.athlete.id}&selected_date=2026-04-18"
        )

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertFalse(payload["ran"])
        self.assertEqual(payload["reason"], "ai_analysis_failed")
        self.assertIsNone(get_latest_health_ai_analysis_for_date(self.db, self.athlete.id, date(2026, 4, 18)))


if __name__ == "__main__":
    unittest.main()
