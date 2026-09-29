"""
金枢 3.0 - OpenHarness 真实集成适配器
=======================================
将香港大学 HKUDS 开源的 OpenHarness 框架接入 L2 Worker 的内层 ReAct 循环。

分层架构：
  外层（LangGraph）：多智能体图拓扑编排 + HiTL Checkpoint 异步审批挂起/唤醒
  内层（OpenHarness）：单 Worker 内 we 里的 Agent Loop / 上下文压缩 / 工具执行沙箱

核心类：
  JinShuToolAdapter  —— 将金枢 ToolSpec 包装成 OpenHarness BaseTool
  build_oh_registry  —— 构建 OpenHarness ToolRegistry（含工具过滤）
  ApprovalRequired   —— 异常信号：高危工具触发时抛出，通知 LangGraph 挂起
  run_oh_worker      —— 驱动 OpenHarness run_query 并将事件翻译为金枢 NDJSON
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from pydantic import BaseModel

# ── OpenHarness 核心导入 ───────────────────────────────────────────
from openharness.api.openai_client import OpenAICompatibleClient
from openharness.engine.query import run_query, QueryContext
from openharness.engine.messages import ConversationMessage
from openharness.engine.stream_events import (
    AssistantTextDelta,
    ToolExecutionStarted,
    ToolExecutionCompleted,
    AssistantTurnComplete,
    StatusEvent,
    ErrorEvent,
    CompactProgressEvent,
)
from openharness.permissions.checker import PermissionChecker, PermissionSettings
from openharness.permissions.modes import PermissionMode
from openharness.tools.base import BaseTool, ToolRegistry as OHToolRegistry, ToolResult, ToolExecutionContext

# ── 金枢自研工具注册中心 ──────────────────────────────────────────
from engine.tools import registry as jinshu_registry
from engine.tools.base import ToolSpec

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# ── LLM 配置（遵循 AGENTS.md 规范，从环境变量读取） ─────────────────
def get_llm_config():
    return {
        "api_key": os.getenv("OPENAI_API_KEY", "").strip(),
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1"),
        "model": os.getenv("LLM_MODEL", "Qwen/QwQ-32B"),
        "max_tokens": 8192,
        "cwd": Path(os.getenv("JINSHU_WORKDIR", "."))
    }


# ─────────────────────────────────────────────────────────────────
# 1. 异常信号与状态追踪：通知外层 LangGraph 触发 HiTL 审批
# ─────────────────────────────────────────────────────────────────

class ApprovalRequired(Exception):
    """
    高危工具请求审批时抛出。
    外层 LangGraphWorkerNode 捕获此异常，将执行流序列化并通过
    LangGraph Checkpoint 挂起，等待 Web 端异步审批后唤醒。
    """
    def __init__(self, tool_name: str, tool_args: dict):
        self.tool_name = tool_name
        self.tool_args = tool_args
        super().__init__(f"Approval required for dangerous tool: {tool_name}")


class ApprovalState:
    """追踪当前 Query 周期内触发权限确认的工具入参"""
    def __init__(self):
        self.last_arguments: dict = {}


# ─────────────────────────────────────────────────────────────────
# 2. 工具适配器：将金枢 ToolSpec → OpenHarness BaseTool
# ─────────────────────────────────────────────────────────────────

def _json_schema_to_pydantic(schema: dict, tool_name: str) -> type[BaseModel]:
    """
    将 JSON Schema（parameters 字段）动态转换为 Pydantic BaseModel。
    OpenHarness 的 BaseTool.input_model 必须 be Pydantic Model。
    """
    from pydantic import create_model, Field as PydanticField

    properties: dict = schema.get("properties", {})
    required: list  = schema.get("required", [])

    field_definitions: dict[str, Any] = {}
    for field_name, field_schema in properties.items():
        py_type: type = str  # 默认 str
        json_type = field_schema.get("type", "string")
        if json_type == "integer":
            py_type = int
        elif json_type == "number":
            py_type = float
        elif json_type == "boolean":
            py_type = bool
        elif json_type == "array":
            py_type = list
        elif json_type == "object":
            py_type = dict

        description = field_schema.get("description", "")
        if field_name in required:
            field_definitions[field_name] = (py_type, PydanticField(description=description))
        else:
            default = field_schema.get("default", None)
            field_definitions[field_name] = (Optional[py_type], PydanticField(default=default, description=description))

    model_cls = create_model(f"{tool_name.title().replace('_', '')}Input", **field_definitions)
    return model_cls


class JinShuToolAdapter(BaseTool):
    """
    将金枢 ToolSpec 包装为 OpenHarness BaseTool。
    OpenHarness 的 run_query 通过此适配器调用金枢自研工具。
    """

    def __init__(self, spec: ToolSpec, approval_state: ApprovalState):
        self._spec = spec
        self.name = spec.name
        self.description = spec.description
        self.approval_state = approval_state
        self.input_model = _json_schema_to_pydantic(
            spec.parameters.get("properties") and spec.parameters or {"properties": {}, "required": []},
            spec.name
        )

    def is_read_only(self, arguments: BaseModel) -> bool:
        """
        判断工具是否为只读。
        对于 requires_approval (DANGER) 级别的工具，返回 False 以便触发 PermissionChecker evaluate，
        从而将控制流交由自定义的 permission_prompt 进行拦截。
        同时保存最后一次评估的参数，供审批拦截门使用。
        """
        if self._spec.requires_approval:
            self.approval_state.last_arguments = arguments.model_dump(exclude_none=True)
            return False
        return True

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        """
        调用金枢工具函数，附带自适应上下文压缩 (Context Compaction)。
        当工具产生数万字符的大型监控遥测或日志转储时，自动修剪冗余，防止上下文窗口溢出。
        """
        kwargs = arguments.model_dump(exclude_none=True)
        try:
            fn = self._spec.fn
            if inspect.iscoroutinefunction(fn):
                result = await fn(**kwargs)
            else:
                result = await asyncio.get_event_loop().run_in_executor(None, lambda: fn(**kwargs))
            
            res_str = str(result)
            # 动态上下文压缩保护：阈值 3500 字符
            if len(res_str) > 3500:
                head = res_str[:1800]
                tail = res_str[-1200:]
                omitted_len = len(res_str) - 3000
                res_str = (
                    f"{head}\n\n"
                    f"⚠️ ... [金枢 Phase 1 上下文动态压缩：已自动折叠中间 {omitted_len} 字符非关键冗余日志，保留首尾关键异常特征] ...\n\n"
                    f"{tail}"
                )
            return ToolResult(output=res_str)
        except Exception as e:
            logger.error(f"[JinShuToolAdapter] {self.name} 执行失败: {e}")
            return ToolResult(output=f"❌ 工具 '{self.name}' 执行异常：{str(e)}", is_error=True)



# ─────────────────────────────────────────────────────────────────
# 3. OpenHarness ToolRegistry 构建器
# ─────────────────────────────────────────────────────────────────

def build_oh_registry(allowed_tools: list[str], approval_state: ApprovalState) -> OHToolRegistry:
    """
    从金枢工具注册中心中过滤出 Worker 被允许的工具集，
    并将其包装为 OpenHarness ToolRegistry。
    """
    oh_registry = OHToolRegistry()
    for tool_name in allowed_tools:
        spec = jinshu_registry.get_tool(tool_name)
        if spec:
            oh_registry.register(JinShuToolAdapter(spec, approval_state))
        else:
            logger.warning(f"[build_oh_registry] 工具 '{tool_name}' 未在金枢注册表中找到，跳过。")
    return oh_registry


# ─────────────────────────────────────────────────────────────────
# 4. 自定义审批钩子：DANGER 工具 → 抛出信号给 LangGraph HiTL
# ─────────────────────────────────────────────────────────────────

class JinShuApprovalPrompt:
    """
    替代 OpenHarness 的本地命令行审批弹窗。
    当 DANGER 级别工具即将执行时，抛出 ApprovalRequired 信号，
    由外层 LangGraphWorkerNode 捕获后序列化为 LangGraph Checkpoint 挂起。
    """
    def __init__(self, approval_state: ApprovalState):
        self.approval_state = approval_state

    async def __call__(self, tool_name: str, reason: str) -> bool:
        """
        OpenHarness 将在执行每个需要确认的工具前调用此回调。
        直接抛出 ApprovalRequired 异常以挂起执行流。
        """
        # 抛出信号，让外层 LangGraph Worker 捕获并触发 HiTL 中断
        raise ApprovalRequired(
            tool_name=tool_name,
            tool_args=self.approval_state.last_arguments
        )


# ─────────────────────────────────────────────────────────────────
# 5. 核心驱动函数：调用 OpenHarness run_query，翻译事件流
# ─────────────────────────────────────────────────────────────────

async def run_oh_worker(
    agent_id: str,
    system_prompt: str,
    allowed_tools: list[str],
    conversation_messages: list[ConversationMessage],
) -> AsyncIterator[dict]:
    """
    使用 OpenHarness 的 run_query 驱动 L2 Worker ReAct 内层循环。
    将 OpenHarness StreamEvent 实时翻译为金枢 NDJSON 事件格式，
    供前端消费和 LangGraph 证据链归集。

    Yields:
        金枢 NDJSON 格式的事件 dict
    """
    cfg = get_llm_config()
    if not cfg["api_key"]:
        yield {
            "event": "final_chunk",
            "expert": agent_id,
            "text": "❌ [OpenHarness] 未配置 OPENAI_API_KEY，无法启动 Agent Loop。"
        }
        return

    # ── 构建 OpenHarness 组件 ─────────────────────────────────────

    api_client = OpenAICompatibleClient(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
    )

    approval_state = ApprovalState()
    oh_registry = build_oh_registry(allowed_tools, approval_state)

    # 过滤出所有不需要审批的工具放行
    non_danger_allowed_tools = []
    for t_name in allowed_tools:
        spec = jinshu_registry.get_tool(t_name)
        if spec and not spec.requires_approval:
            non_danger_allowed_tools.append(t_name)

    # 使用 DEFAULT 权限模式：不需要确认的工具在 allowed_tools 里放行，需要确认的工具 fall through
    perm_settings = PermissionSettings(
        mode=PermissionMode.DEFAULT,
        allowed_tools=non_danger_allowed_tools,
    )
    perm_checker = PermissionChecker(settings=perm_settings)

    approval_prompt = JinShuApprovalPrompt(approval_state)

    ctx = QueryContext(
        api_client=api_client,
        tool_registry=oh_registry,
        permission_checker=perm_checker,
        cwd=cfg["cwd"],
        model=cfg["model"],
        system_prompt=system_prompt,
        max_tokens=cfg["max_tokens"],
        max_turns=8,
        permission_prompt=approval_prompt,
        tool_metadata={},
    )

    # ── 驱动 OpenHarness Agent Loop，翻译事件 ──────────────────────

    final_text = ""

    try:
        async for event, _usage in run_query(ctx, conversation_messages):

            if isinstance(event, AssistantTextDelta):
                # LLM 流式文本（思维链 / 推理过程）
                yield {
                    "event": "thought",
                    "expert": agent_id,
                    "text": event.text,
                }

            elif isinstance(event, ToolExecutionStarted):
                yield {
                    "event": "tool_call",
                    "expert": agent_id,
                    "name": event.tool_name,
                    "args": event.tool_input,
                }

            elif isinstance(event, ToolExecutionCompleted):
                yield {
                    "event": "observation",
                    "expert": agent_id,
                    "result": event.output,
                    "is_error": event.is_error,
                }

            elif isinstance(event, AssistantTurnComplete):
                # 提取最终文本回复与隐式思维链
                turn_text = ""
                for block in event.message.content:
                    if hasattr(block, "text"):
                        turn_text += block.text
                final_text += turn_text
                
                # 若底层推理模型输出了思维链内容，单独发射结构化 reasoning 事件
                raw_reasoning = getattr(event.message, "_reasoning", None)
                if raw_reasoning:
                    yield {
                        "event": "reasoning_chain",
                        "expert": agent_id,
                        "thought": raw_reasoning,
                    }

                yield {
                    "event": "final_chunk",
                    "expert": agent_id,
                    "text": turn_text,
                }

            elif isinstance(event, CompactProgressEvent):
                yield {
                    "event": "compact",
                    "expert": agent_id,
                    "text": "[OpenHarness Auto-Compact] 上下文已自动压缩，保留最近关键证据。",
                }

            elif isinstance(event, StatusEvent):
                logger.debug(f"[OH Status] {agent_id}: {event}")

            elif isinstance(event, ErrorEvent):
                yield {
                    "event": "final_chunk",
                    "expert": agent_id,
                    "text": f"❌ [OpenHarness Error] {event}",
                }

    except ApprovalRequired as exc:
        # DANGER 工具触发人工审批，将信号传递给外层 LangGraph
        yield {
            "event": "approval_required",
            "expert": agent_id,
            "tool":  exc.tool_name,
            "args":  exc.tool_args,
        }

    except Exception as exc:
        logger.exception(f"[run_oh_worker] {agent_id} 执行异常: {exc}")
        yield {
            "event": "final_chunk",
            "expert": agent_id,
            "text": f"❌ [{agent_id}] OpenHarness 执行异常：{str(exc)}",
        }
