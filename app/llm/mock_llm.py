"""Deterministic offline LLM for demo mode and tests."""

from __future__ import annotations

import json
import re

from app.llm.base import BaseLLM


class MockLLM(BaseLLM):
    """Rule-based LLM substitute that returns predictable JSON/text."""

    provider_name = "mock"

    def is_available(self) -> bool:
        return True

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        sys = system_prompt.lower()
        if "router" in sys or "route" in sys and "task" in sys:
            return self._route_response(user_prompt)
        if "clarification" in sys:
            return json.dumps({"questions": []}, ensure_ascii=False)
        if "visualspec" in sys.replace("_", "") or "visual spec" in sys:
            return json.dumps(
                {
                    "title": "演示视觉标题",
                    "style": "清晰专业",
                    "purpose": "传达核心信息",
                    "scenario": "演示场景",
                    "key_elements": ["主体", "标题", "辅助图形"],
                },
                ensure_ascii=False,
            )
        if "critic" in sys:
            return json.dumps(
                {"extra_comments": ["mock critic"], "extra_suggestions": ["mock suggestion"]},
                ensure_ascii=False,
            )
        if "revision" in sys:
            return json.dumps(
                {"revised_prompt": user_prompt[:500] + " [revised]"}, ensure_ascii=False
            )
        if "prompt" in sys:
            return json.dumps(
                {"prompt": f"Subject: demo. Context: {user_prompt[:120]}"}, ensure_ascii=False
            )
        return json.dumps(
            {"purpose": "演示", "main_subject": "演示主体", "style": "简洁"}, ensure_ascii=False
        )

    @staticmethod
    def _route_response(user_prompt: str) -> str:
        text = user_prompt.lower()
        scores = {
            "ecommerce_banner": len(re.findall(r"商品|促销|电商|banner|product|sale", text)),
            "academic_figure": len(
                re.findall(r"论文|流程图|pipeline|diagram|学术|framework", text)
            ),
            "ppt_visual": len(re.findall(r"ppt|汇报|infographic|教学|教育|presentation", text)),
        }
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            # No domain signal: stay honest with a low-confidence best guess so
            # the router can request clarification instead of asserting a type.
            return json.dumps(
                {
                    "task_type": "ppt_visual",
                    "confidence": 0.2,
                    "reasoning": "mock llm: no domain signal detected",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {"task_type": best, "confidence": 0.75, "reasoning": "mock llm routing"},
            ensure_ascii=False,
        )
