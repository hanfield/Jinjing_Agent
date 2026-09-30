"""
金枢 3.0 (Jin-Shu OS) - LangGraph 驾驭工程层
=============================================
基于 LangGraph StateGraph 重构的多智能体编排引擎。
对外暴露与原 MultiAgentOrchestrator 完全兼容的 API 接口，
实现零改动替换 main_v2.py 中的 engine 引用。
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .streaming import LangGraphOrchestrator

_orchestrator = None

def __getattr__(name: str):
    global _orchestrator
    if name == "LangGraphOrchestrator":
        from .streaming import LangGraphOrchestrator
        return LangGraphOrchestrator
    elif name == "multi_agent_orchestrator":
        if _orchestrator is None:
            from .streaming import LangGraphOrchestrator
            _orchestrator = LangGraphOrchestrator()
        return _orchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["multi_agent_orchestrator", "LangGraphOrchestrator"]
