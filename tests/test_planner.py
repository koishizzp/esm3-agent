from __future__ import annotations

import unittest
from unittest.mock import Mock

from protein_agent.agent.planner import LLMPlanner
from protein_agent.config.settings import Settings


class PlannerFallbackTests(unittest.TestCase):
    def test_plan_falls_back_when_llm_request_raises(self) -> None:
        planner = LLMPlanner(Settings(openai_api_key="dummy", llm_model="gpt-test"))
        planner.client = Mock()
        planner.client.responses.create.side_effect = RuntimeError("auth_unavailable: no auth available")

        plan = planner.plan("Design an improved GFP and iteratively optimize it")

        self.assertEqual(plan["workflow"], "iterative_protein_optimization")
        self.assertEqual(plan["target"], "GFP")
        self.assertIn("generate_candidates", plan["steps"])


if __name__ == "__main__":
    unittest.main()
