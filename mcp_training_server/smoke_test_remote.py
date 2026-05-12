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
                "get_session_feedback_by_date",
                "get_week_context",
                "get_last_activity_feedback",
                "get_next_session_context",
            }
            missing = sorted(required.difference(tool_names))
            if missing:
                raise RuntimeError(f"Faltan tools: {missing}")

            result = await session.call_tool("get_session_feedback_by_date", {"date": "02/05/26"})
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
