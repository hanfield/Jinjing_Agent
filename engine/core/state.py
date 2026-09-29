"""
金枢 3.0 (Jin-Shu OS) - LangGraph 全局状态模式定义 (Python 3.9 兼容版)
========================================================================
JinShuState 是整个 StateGraph 的"神经中枢"，完全替代原有的 Blackboard 单例模式。
"""

import operator
from typing import Annotated, Any, TypedDict, List, Dict, Optional


class EvidenceItem(TypedDict):
    """单条结构化风险判定证据链"""
    source_agent: str
    affected_target: str
    ttf_minutes: int
    confidence: float
    risk_summary: str
    timestamp: float


class PendingApproval(TypedDict):
    """挂起等待审批的高危操作描述"""
    agent_id: str
    tool_name: str
    tool_args: dict
    call_id: str
    messages_snapshot: list


class JinShuState(TypedDict):
    """金枢全局图状态"""
    user_message: str
    experts_to_invoke: List[str]
    experts_completed: List[str]
    environment_status: Dict[str, Any]
    affected_hosts: List[str]
    security_locks: Dict[str, bool]
    overall_status: str
    evidence_chain: Annotated[List[EvidenceItem], operator.add]
    stream_events: Annotated[List[dict], operator.add]
    pending_approval: Optional[PendingApproval]
    approval_result: Optional[bool]
    final_summary: str


def make_initial_state(user_message: str) -> JinShuState:
    """构造初始空白状态"""
    return JinShuState(
        user_message=user_message,
        experts_to_invoke=[],
        experts_completed=[],
        environment_status={},
        affected_hosts=[],
        security_locks={},
        overall_status="NORMAL",
        evidence_chain=[],
        stream_events=[],
        pending_approval=None,
        approval_result=None,
        final_summary="",
    )
