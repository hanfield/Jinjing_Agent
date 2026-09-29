"""
金枢 2.0 (Jin-Shu OS) - Base Agent Entity & Lifecycle State Machine
===================================================================
实现真正的独立智能体实体抽象。每个智能体拥有独立的生命周期状态机、独立的内存空间
以及专属的工具注册表，彻底从底层原语级别解耦单体架构。
"""

import os
from enum import Enum
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import httpx


class AgentState(Enum):
    """智能体生命周期状态机定义"""
    INITIALIZING = "initializing"          # 正在加载人设与专属权限
    IDLE = "idle"                          # 空闲就绪
    THINKING = "thinking"                  # 正在调用大模型推演
    WAITING_FOR_TOOL = "waiting_for_tool"  # 正在等待底层探针返回
    WAITING_FOR_APPROVAL = "waiting_for_approval" # 正在等待主管授权流
    COMPLETED = "completed"                # 推演圆满完成
    FAILED = "failed"                      # 熔断或执行失败


@dataclass
class AgentMemory:
    """独立智能体内部内存模型"""
    agent_id: str
    short_term_history: List[dict] = field(default_factory=list) # 单次排障对局上下文
    long_term_insights: Dict[str, Any] = field(default_factory=dict) # 领域特化经验沉淀


class BaseAgent:
    """殿堂级智能体实体基类"""

    def __init__(self, agent_id: str, name: str, system_prompt: str, allowed_tools: List[str] = None):
        self.agent_id = agent_id
        self.name = name
        self.system_prompt = system_prompt
        self.allowed_tools = allowed_tools or []
        
        # 运行时状态机与内存隔离
        self.state: AgentState = AgentState.INITIALIZING
        self.memory: AgentMemory = AgentMemory(agent_id=agent_id)
        self.last_error: Optional[str] = None
        self.state = AgentState.IDLE

        # 独立异步客户端池
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
        self.model = os.getenv("LLM_MODEL", "Qwen/QwQ-32B")
        print(f"[DEBUG BaseAgent] agent_id={self.agent_id} base_url={self.base_url} model={self.model}")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        headers["Connection"] = "close"
        self._client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=60.0)

    def transition_to(self, new_state: AgentState):
        """严格的状态机流转引擎"""
        # 可以扩展状态流转鉴权机制
        self.state = new_state

    async def call_llm(self, messages: List[dict], tools_schema: List[dict] = None) -> dict:
        """底层大模型调用封装"""
        self.transition_to(AgentState.THINKING)
        payload = {"model": self.model, "messages": messages, "temperature": 0.1}
        if tools_schema:
            payload["tools"] = tools_schema
        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.last_error = str(e)
            self.transition_to(AgentState.FAILED)
            raise e

    async def close(self):
        await self._client.aclose()
