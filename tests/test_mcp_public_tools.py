from __future__ import annotations

import ast
import unittest
from pathlib import Path


class McpPublicToolsTests(unittest.TestCase):
    def test_public_allowlist_matches_expected_surface(self) -> None:
        source = Path("mcp_training_server/server.py").read_text(encoding="utf-8")
        module = ast.parse(source)

        public_names: list[str] = []
        for node in module.body:
            tuple_node = None
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "PUBLIC_MCP_TOOL_NAMES":
                        tuple_node = node.value
                        break
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "PUBLIC_MCP_TOOL_NAMES":
                tuple_node = node.value
            if isinstance(tuple_node, ast.Tuple):
                for elt in tuple_node.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        public_names.append(elt.value)

        self.assertTrue(public_names, "No se encontro PUBLIC_MCP_TOOL_NAMES en server.py")
        public_set = set(public_names)

        required = {
            "get_session_metrics_json",
            "get_week_metrics_json",
            "preview_plan_import",
            "commit_plan_import",
            "verify_plan_import",
        }
        forbidden = {
            "get_activity_detail",
            "compare_planned_vs_done",
            "get_session_analysis_payload",
            "get_latest_weekly_analysis",
            "get_week_load_summary",
        }

        self.assertFalse(required.difference(public_set))
        self.assertFalse(forbidden.intersection(public_set))


if __name__ == "__main__":
    unittest.main()
