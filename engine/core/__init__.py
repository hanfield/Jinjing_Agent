"""
金枢 3.0 (Jin-Shu OS) - LangGraph 驾驭工程层
=============================================
基于 LangGraph StateGraph 重构的多智能体编排引擎。
对外暴露与原 MultiAgentOrchestrator 完全兼容的 API 接口，
实现零改动替换 main_v2.py 中的 engine 引用。
"""

from .streaming import LangGraphOrchestrator

# 全局单例 —— 与原 multi_agent_orchestrator 接口完全兼容
multi_agent_orchestrator = LangGraphOrchestrator()

__all__ = ["multi_agent_orchestrator", "LangGraphOrchestrator"]
