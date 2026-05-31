from __future__ import annotations

import asyncio
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _server_url() -> str:
    raw_url = (os.getenv("MCP_REMOTE_URL") or "").strip()
    if not raw_url:
        raise RuntimeError("MCP_REMOTE_URL no esta configurado.")
    return raw_url


async def _run() -> None:
    url = _server_url()
    async with streamablehttp_client(url) as (read, write, _session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = [tool.name for tool in tools.tools]
            print("TOOLS", tool_names)

            required = {
                "get_athletes",
                "get_recent_activities",
                "get_health_summary",
                "get_day_plan",
                "get_week_plan",
                "get_remaining_week_plan",
                "get_today_remaining_sessions",
                "get_next_planned_session",
                "get_today_coach_briefing",
                "get_training_dashboard",
                "get_fatigue_risk_summary",
                "get_session_metrics_json",
                "get_my_session_metrics_json",
                "get_week_metrics_json",
                "get_my_week_metrics_json",
                "preview_plan_import",
                "verify_plan_import",
                "commit_plan_import",
            }
            missing = sorted(required.difference(tool_names))
            if missing:
                raise RuntimeError(f"Faltan tools: {missing}")

            forbidden = {
                "get_activity_detail",
                "get_latest_weekly_analysis",
                "get_week_load_summary",
                "get_my_week_load_summary",
                "get_session_analysis_payload",
                "get_my_session_analysis_payload",
                "compare_planned_vs_done",
                "compare_my_planned_vs_done",
                "get_week_comparison",
                "get_training_load_trend",
                "get_week_strategy_summary",
                "get_training_decision_context",
                "get_optional_session_impact",
            }
            exposed_forbidden = sorted(forbidden.intersection(tool_names))
            if exposed_forbidden:
                raise RuntimeError(f"Tools publicas inesperadas: {exposed_forbidden}")

            result = await session.call_tool("get_athletes", {})
            is_error = result.isError if hasattr(result, "isError") else getattr(result, "is_error", None)
            print("IS_ERROR", is_error)
            if is_error:
                text_items = [getattr(item, "text", "") for item in result.content]
                raise RuntimeError("Error llamando tool remota: " + " ".join(text_items))
            for item in result.content:
                text = getattr(item, "text", "")
                if text:
                    print(text[:400])
                    break


def main() -> int:
    asyncio.run(_run())
    print("Smoke test remoto MCP completado correctamente.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
