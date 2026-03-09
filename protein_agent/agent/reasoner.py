"""Conversational analysis for protein design results."""
from __future__ import annotations

import json
import logging
from typing import Any

try:
    from openai import OpenAI
except Exception:  # noqa: BLE001
    OpenAI = None

from protein_agent.config.settings import Settings

LOGGER = logging.getLogger(__name__)


def _score_value(item: dict[str, Any]) -> float:
    value = item.get("score")
    return float(value) if isinstance(value, (int, float)) else float("-inf")


class ResultReasoner:
    """Explains current candidates using an LLM when available, with deterministic fallback."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = None
        if settings.openai_api_key:
            if OpenAI is None:
                LOGGER.warning("openai package unavailable; using fallback result reasoner.")
            else:
                self.client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)

    def reply(
        self,
        message: str,
        latest_result: dict[str, Any] | None = None,
        conversation: list[dict[str, str]] | None = None,
        current_mode: str = "design",
        previous_best_sequence: str | None = None,
    ) -> str:
        fallback = self._fallback_reply(message, latest_result, current_mode, previous_best_sequence)
        if not self.client:
            return fallback

        payload = {
            "message": message,
            "current_mode": current_mode,
            "previous_best_sequence": previous_best_sequence,
            "conversation": self._compact_conversation(conversation or []),
            "latest_result": self._compact_result(latest_result),
        }
        try:
            response = self.client.responses.create(
                model=self.settings.llm_model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are a protein-design copilot for a wet-lab team. "
                            "Answer in concise Chinese. Ground your answer in the provided result object. "
                            "Reason actively, but clearly label any inference as 推断. "
                            "Do not pretend scoring equals experimental truth. "
                            "If the user asks why a candidate is better for validation, explain relative ranking, "
                            "stability of the optimization trajectory, constraint coverage, uncertainty, and next validation steps. "
                            "If no result is available, say that directly and ask for a run first."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
            )
            text = (response.output_text or "").strip()
            return text or fallback
        except Exception:  # noqa: BLE001
            LOGGER.exception("LLM result reasoning failed; using fallback.")
            return fallback

    def _compact_conversation(self, conversation: list[dict[str, str]]) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for msg in conversation[-8:]:
            role = str(msg.get("role") or "user")
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            items.append({"role": role, "content": content[:1200]})
        return items

    def _compact_result(self, latest_result: dict[str, Any] | None) -> dict[str, Any] | None:
        normalized = self._normalize_result(latest_result)
        if not normalized:
            return None
        history = normalized.get("history") or []
        ranked = sorted(history, key=_score_value, reverse=True)
        top_records: list[dict[str, Any]] = []
        for item in ranked[:6]:
            top_records.append(
                {
                    "score": item.get("score"),
                    "iteration": item.get("iteration"),
                    "mutation_history": item.get("mutation_history") or [],
                    "sequence": item.get("sequence") or "",
                }
            )
        return {
            "task": normalized.get("task"),
            "plan": normalized.get("plan") or {},
            "input_context": normalized.get("input_context") or {},
            "best_sequences": normalized.get("best_sequences") or None,
            "generation_stats": normalized.get("generation_stats") or [],
            "history_top": top_records,
            "history_count": len(history),
        }

    def _normalize_result(self, latest_result: dict[str, Any] | None) -> dict[str, Any] | None:
        if not latest_result:
            return None
        if latest_result.get("best_sequences"):
            return latest_result
        best_candidate = latest_result.get("best_candidate")
        if not isinstance(best_candidate, dict):
            return latest_result
        all_candidates = latest_result.get("all_candidates") or []
        history: list[dict[str, Any]] = []
        for item in all_candidates:
            if not isinstance(item, dict):
                continue
            mutation_history: list[str] = []
            reason = item.get("reason")
            if isinstance(reason, str) and reason.strip():
                mutation_history.append(reason.strip())
            history.append(
                {
                    "sequence": item.get("sequence") or "",
                    "score": item.get("score"),
                    "iteration": item.get("round"),
                    "mutation_history": mutation_history,
                }
            )
        best_mutation_history: list[str] = []
        best_reason = best_candidate.get("reason")
        if isinstance(best_reason, str) and best_reason.strip():
            best_mutation_history.append(best_reason.strip())
        return {
            "task": latest_result.get("task") or latest_result.get("objective") or "",
            "plan": latest_result.get("plan") or {},
            "input_context": latest_result.get("input_context") or {},
            "best_sequences": {
                "sequence": best_candidate.get("sequence") or "",
                "score": best_candidate.get("score"),
                "iteration": best_candidate.get("round"),
                "mutation_history": best_mutation_history,
            },
            "generation_stats": latest_result.get("generation_stats") or [],
            "history": history,
        }

    def _fallback_reply(
        self,
        message: str,
        latest_result: dict[str, Any] | None,
        current_mode: str,
        previous_best_sequence: str | None,
    ) -> str:
        normalized = self._normalize_result(latest_result)
        if not normalized:
            return (
                "我现在还没有可引用的当前结果，所以没法严谨地解释“为什么这个候选更适合验证”。\n"
                "先跑一次设计、逆折叠或功能条件生成后，我就能基于右侧结果继续分析。"
            )

        best = normalized.get("best_sequences") or {}
        if not best:
            return (
                "当前结果里还没有解析出可用的最佳候选，所以我没法给出可靠解释。\n"
                "建议先检查右侧完整 JSON，确认 `best_sequences` 和 `history` 是否正常返回。"
            )

        history = normalized.get("history") or []
        ranked = sorted(history, key=_score_value, reverse=True)
        best_score = float(best.get("score") or 0)
        best_iteration = best.get("iteration") or "-"
        second_score = None
        if len(ranked) > 1:
            second_score = float(ranked[1].get("score") or 0)

        generation_stats = normalized.get("generation_stats") or []
        input_context = normalized.get("input_context") or {}
        mutation_history = best.get("mutation_history") or []
        reasons: list[str] = []

        reasons.append(
            f"如果只看当前这批结果，这个候选更适合优先验证，最直接的原因是它目前排在第一：score = {best_score:.4f}，来自第 {best_iteration} 轮。"
        )

        if second_score is not None:
            delta = best_score - second_score
            reasons.append(
                f"和当前第二名相比，它还高出 {delta:.4f}。这说明它不是“勉强领先”，而是在这轮排序里有明确优势。"
            )
        elif ranked:
            reasons.append("当前可直接比较的候选不多，所以它至少是现有结果里最合理的首个验证入口。")

        if generation_stats:
            first_best = float(generation_stats[0].get("best_score") or 0)
            last_best = float(generation_stats[-1].get("best_score") or 0)
            if last_best > first_best:
                reasons.append(
                    f"从代际轨迹看，best score 从 {first_best:.4f} 提升到 {last_best:.4f}，说明优化过程不是随机抖动，当前最佳候选是经过筛选压力逐步浮上来的。"
                )
            else:
                reasons.append("代际分数没有明显继续走高，所以这个候选更像是当前搜索空间里的相对最优，而不是已经充分收敛后的绝对最优。")

        if mutation_history:
            reasons.append(
                f"它不是单纯的初始 seed，而是经历了 {len(mutation_history)} 步变异/筛选痕迹后留下来的候选，这通常比直接拿起始序列去做实验更有验证价值。"
            )

        constraint_bits: list[str] = []
        if input_context.get("input_sequence"):
            constraint_bits.append("参考序列")
        if input_context.get("input_pdb_path") or input_context.get("input_pdb_text"):
            constraint_bits.append("结构约束")
        if (input_context.get("input_function_keywords") or []) or (input_context.get("input_function_annotations") or []):
            constraint_bits.append("功能约束")
        if constraint_bits:
            reasons.append(
                f"另外，它是在 {'、'.join(constraint_bits)} 这些条件下被筛出来的，不只是对单一评分函数取最大值，所以更适合作为“先验证哪个”的候选。"
            )

        if previous_best_sequence:
            current_sequence = str(best.get("sequence") or "")
            if current_sequence and current_sequence != previous_best_sequence:
                reasons.append("推断：它能替代上一轮最佳序列，意味着在当前评价函数下，新变体至少带来了可观的排序收益。")

        reasons.append(
            "但要注意，这里的“更适合验证”只代表它在当前评分体系和当前候选集合里更靠前，不等于它已经被证明在湿实验中一定最好。"
        )

        if current_mode == "design":
            reasons.append(
                "如果你现在要落地验证，我建议优先做表达/可溶性、基础功能读出、再加上与第二名的并行对照，这样最能检验当前排序是否靠谱。"
            )
        elif current_mode == "inverse_fold":
            reasons.append("如果是逆折叠场景，建议优先核对序列是否满足结构约束，再做结构一致性与表达测试。")
        else:
            reasons.append("如果是功能条件生成场景，建议先看功能约束是否满足，再安排最小成本的体外验证。")

        if "为什么" in message or "适合验证" in message or "理由" in message:
            return "\n".join(reasons)
        return "\n".join(reasons[:4] + reasons[-2:])
