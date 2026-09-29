"""
金枢 3.0 - 护栏节点 (Guardrail Node - Python 3.9 兼容版)
==========================================================
图的入口第一节点。负责输入安全拦截。
"""

import re
from typing import Literal, List, Tuple, Any

from engine.core.state import JinShuState

# ── 禁止模式库 ──────────────────────────────────────────────────────
_FORBIDDEN_PATTERNS: List[Tuple[Any, str]] = [
    (
        re.compile(r"(?i)ignore\s+all\s+previous\s+instructions"),
        "Prompt 注入攻击：尝试覆盖系统指令",
    ),
    (
        re.compile(r"(?i)(system\s+prompt|你的\s*prompt|你的系统提示)"),
        "探测系统提示词攻击",
    ),
    (
        re.compile(r"(?i)(jailbreak|越狱|绕过限制|忽略规则)"),
        "越狱指令检测",
    ),
    (
        re.compile(r"(?i)(rm\s+-rf\s+/|DROP\s+TABLE|DELETE\s+FROM\s+\w+\s+WHERE\s+1=1)"),
        "高危破坏性指令注入",
    ),
]


def _validate_input(prompt: str) -> Tuple[bool, str]:
    """
    返回 (is_safe: bool, reason: str)。
    """
    for pattern, reason in _FORBIDDEN_PATTERNS:
        if pattern.search(prompt):
            return False, reason
    return True, ""


# ── LangGraph 节点函数 ────────────────────────────────────────────────

def guardrail_node(state: JinShuState) -> dict:
    """
    护栏节点：图执行的第一道关卡。
    """
    user_message = state["user_message"]
    is_safe, reason = _validate_input(user_message)

    if is_safe:
        return {
            "stream_events": [
                {"event": "guardrail_pass", "expert": "Guardrail"}
            ]
        }
    else:
        block_event = {
            "event": "final_chunk",
            "expert": "Guardrail",
            "text": f"❌ 高危拦截：输入包含禁止指令（{reason}），已阻断本次请求。",
            "_blocked": True,
        }
        return {
            "stream_events": [block_event],
            "final_summary": f"[安全拦截] {reason}",
            "overall_status": "CRITICAL",
        }


def route_after_guardrail(state: JinShuState) -> Literal["supervisor", "__end__"]:
    """
    护栏后的条件路由函数。
    """
    events = state.get("stream_events", [])
    if events and events[-1].get("_blocked"):
        return "__end__"
    return "supervisor"
