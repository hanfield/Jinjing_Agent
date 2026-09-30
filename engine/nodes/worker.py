"""
金枢 3.0 - Worker 智能体节点 (Worker Agent Node)
===================================================
封装通用的 ReAct 循环，支持 MCP 客户端启动、工具调用过滤、
高危指令多级权限拦截 (Human-in-the-Loop) 与证据链投递。

本文件取代原：
  engine/multi_agent/workers.py 的全部 BaseWorkerAgent 执行逻辑。
"""

import json
import time
import inspect
import asyncio
import logging
from typing import List

from engine.core.state import JinShuState, EvidenceItem, PendingApproval
from engine.tools import registry as jinshu_registry
from engine.blackboard import global_blackboard, EvidenceItem as LegacyEvidenceItem

# ── OpenHarness 导入 ──────────────────────────────────────────────
from openharness.engine.messages import ConversationMessage, ToolResultBlock
from engine.agents.openharness_bridge import run_oh_worker

logger = logging.getLogger(__name__)


class LangGraphWorkerNode:
    """封装特定 Worker 的配置与 OpenHarness 运行时"""

    def __init__(self, agent_id: str, name: str, system_prompt: str, allowed_tools: List[str]):
        self.agent_id = agent_id
        self.name = name
        self.system_prompt = system_prompt
        self.allowed_tools = allowed_tools

    async def run(self, state: JinShuState) -> dict:
        """
        运行当前 Worker 的 OpenHarness 循环核心逻辑。
        """
        # 1. 检查是否刚刚从审批中断中恢复
        if state.get("pending_approval") and state["pending_approval"].get("agent_id") == self.agent_id:
            # 说明这个节点之前被挂起了，现在有审批结果
            return await self._resume_after_approval(state)

        # 2. 正常初始化并启动 ReAct 循环
        user_message = state["user_message"]

        # 提取当前 Worker 所需的黑板上下文片段（对应原 Blackboard.get_context_summary 逻辑）
        blackboard_summary = self._get_context_summary(state)
        full_prompt = f"{self.system_prompt}\n\n{blackboard_summary}\n\n请结合上述黑板态势和用户问题，调用可用工具进行推演诊断。"

        events = []
        events.append({"event": "start_thinking", "expert": self.agent_id})

        # 初始化 OpenHarness 消息链，run_oh_worker 中 QueryContext 已经装载了系统提示词
        conversation_messages = [
            ConversationMessage.from_user_text(user_message)
        ]

        return await self._execute_oh_loop(full_prompt, conversation_messages, state, events)

    async def _execute_oh_loop(self, system_prompt: str, conversation_messages: list, state: JinShuState, events: list) -> dict:
        """驱动 OpenHarness 内部 ReAct 执行流，翻译事件并完成最终收盘"""
        final_answer = ""
        pending = None

        try:
            async for ev in run_oh_worker(self.agent_id, system_prompt, self.allowed_tools, conversation_messages):
                events.append(ev)
                if ev["event"] == "final_chunk":
                    final_answer = ev["text"]
                elif ev["event"] == "approval_required":
                    # 🚨 触发 Human-in-the-Loop 中断！
                    # 在最后一条助手的消息中找到触发此 danger 工具调用的 call_id
                    last_msg = conversation_messages[-1]
                    call_id = next((tc.id for tc in last_msg.tool_uses if tc.name == ev["tool"]), "unknown_call_id")

                    pending = PendingApproval(
                        agent_id=self.agent_id,
                        tool_name=ev["tool"],
                        tool_args=ev["args"],
                        call_id=call_id,
                        messages_snapshot=[msg.model_dump() for msg in conversation_messages]
                    )
                    break

        except Exception as e:
            logger.exception(f"Error during OpenHarness loop: {e}")
            events.append({"event": "final_chunk", "expert": self.agent_id, "text": f"\n❌ [{self.agent_id}] OpenHarness 内部异常: {e}"})

        # 如果被审批挂起，直接返回给 LangGraph 状态图
        if pending:
            return {
                "pending_approval": pending,
                "approval_result": None,
                "stream_events": events
            }

        # ── 3. 生成证据与黑板同步 ───────────────────────────────────────
        evidence_chain_updates = []
        if final_answer:
            ttf = 15 if "15分钟" in final_answer or "越界" in final_answer else 60
            conf = 0.95 if "发现靶点" in final_answer or "告警" in final_answer else 0.85
            target = "RACK-A02" if "A02" in final_answer else "SVR-003" if "SVR" in final_answer else "全局设施"

            ev = EvidenceItem(
                source_agent=self.agent_id,
                affected_target=target,
                ttf_minutes=ttf,
                confidence=conf,
                risk_summary=final_answer[:150] + "..." if len(final_answer) > 150 else final_answer,
                timestamp=time.time()
            )
            evidence_chain_updates.append(ev)
            events.append({"event": "blackboard_post", "expert": self.agent_id, "evidence": ev})

            # 更新动环状态等全局黑板参数
            updates = {
                "evidence_chain": evidence_chain_updates,
                "stream_events": events,
                "experts_completed": [self.agent_id],
                "pending_approval": None,
                "approval_result": None
            }
            if ttf <= 15 and conf > 0.8:
                updates["overall_status"] = "CRITICAL"

            # 模拟原 Blackboard.update_environment / add_affected_hosts
            if self.agent_id == "L2_Infra":
                temp = 32.5 if "越界" in final_answer else 24.0
                load = 0.92 if "超载" in final_answer else 0.5
                updates["environment_status"] = {
                    "RACK-A02": {
                        "temp_celsius": temp,
                        "load_ratio": load,
                        "updated_at": time.time()
                    }
                }
                global_blackboard.update_environment("RACK-A02", temp, load)
            elif self.agent_id == "L2_Cloud":
                updates["affected_hosts"] = ["SVR-003"]
                global_blackboard.add_affected_hosts(["SVR-003"])
            elif self.agent_id == "L2_Sec":
                updates["security_locks"] = {"RACK-A02-LOCK": True}
                global_blackboard.set_security_lock("RACK-A02-LOCK", True)

            # 同时向全局传统黑板总线提交证据（保持可观测性评分一致）
            legacy_ev = LegacyEvidenceItem(
                source_agent=self.agent_id,
                affected_target=target,
                ttf_minutes=ttf,
                confidence=conf,
                risk_summary=ev["risk_summary"],
                timestamp=ev["timestamp"]
            )
            global_blackboard.post_evidence(legacy_ev)

            return updates

        return {
            "stream_events": events,
            "experts_completed": [self.agent_id],
            "pending_approval": None,
            "approval_result": None
        }

    async def _resume_after_approval(self, state: JinShuState) -> dict:
        """从高危拦截中审批通过/拒绝后继续执行"""
        pending = state["pending_approval"]
        approved = state["approval_result"]

        events = []
        conversation_messages = [ConversationMessage(**msg) for msg in pending["messages_snapshot"]]
        call_id = pending["call_id"]
        fn_name = pending["tool_name"]
        fn_args = pending["tool_args"]

        if approved:
            try:
                tool = jinshu_registry.get_tool(fn_name)
                if inspect.iscoroutinefunction(tool.fn):
                    res_val = await tool.fn(**fn_args)
                else:
                    res_val = await asyncio.get_event_loop().run_in_executor(None, lambda: tool.fn(**fn_args))
                result_str = f"✅ 用户已授权执行。\n结果: {res_val}"
                is_error = False
            except Exception as e:
                result_str = f"❌ 工具执行失败: {e}"
                is_error = True

            events.append({
                "event": "observation",
                "expert": self.agent_id,
                "result": f"✅ 用户已授权执行。\n结果: {result_str}"
            })
        else:
            result_str = f"❌ 高危操作拦截：用户（前端操作员）明确回绝了此 '{fn_name}' 执行请求。"
            is_error = True
            events.append({
                "event": "observation",
                "expert": self.agent_id,
                "result": result_str
            })

        # 将人工干预结果作为 ToolResult 填回消息历史
        tool_result = ToolResultBlock(
            tool_use_id=call_id,
            content=result_str,
            is_error=is_error
        )
        conversation_messages.append(ConversationMessage(role="user", content=[tool_result]))

        # 重建 full_prompt (即 system_prompt)
        blackboard_summary = self._get_context_summary(state)
        full_prompt = f"{self.system_prompt}\n\n{blackboard_summary}\n\n请结合上述黑板态势和用户问题，调用可用工具进行推演诊断。"

        # 继续 OpenHarness 推演循环
        return await self._execute_oh_loop(full_prompt, conversation_messages, state, events)

    def _get_context_summary(self, state: JinShuState) -> str:
        """
        [上下文修剪引擎 Context Pruning Engine]
        根据目标 Worker 角色，只截取对应的全局黑板切面信息（与 Blackboard.get_context_summary 一致）
        """
        summary_lines = [f"### 📋 全局黑板状态总线摘要 (当前态势: {state.get('overall_status', 'NORMAL')})"]

        if self.agent_id == "L2_Cloud":
            summary_lines.append("#### 🖥️ 云原生与主机态势订阅")
            hosts = state.get("affected_hosts", [])
            summary_lines.append(f"- 受影响主机队列: {', '.join(hosts) if hosts else '暂无直接受影响主机'}")
            infra_ev = [e for e in state.get("evidence_chain", []) if e["source_agent"] == "L2_Infra"]
            for ev in infra_ev:
                summary_lines.append(f"- ⚠️ [底层动环诱因]: 靶点 {ev['affected_target']} 预计 {ev['ttf_minutes']} 分钟内崩溃 ({ev['risk_summary']})")

        elif self.agent_id == "L2_Infra":
            summary_lines.append("#### 🗄️ 动环与基础设施态势订阅")
            summary_lines.append(f"- 环境遥测快照: {json.dumps(state.get('environment_status', {}), ensure_ascii=False)}")

        elif self.agent_id == "L2_Sec":
            summary_lines.append("#### 🔒 安防与合规态势订阅")
            summary_lines.append(f"- 物理/逻辑锁状态: {json.dumps(state.get('security_locks', {}), ensure_ascii=False)}")
            summary_lines.append(f"- 待审批拦截流: {'开启' if state.get('pending_approval') else '无'}")

        # 附加最高置信度的证据
        chain = state.get("evidence_chain", [])
        if chain:
            top_ev = sorted(chain, key=lambda x: x["confidence"], reverse=True)[0]
            summary_lines.append(f"\n#### 🏆 全局最高置信度判定: [{top_ev['source_agent']}] -> {top_ev['risk_summary']}")

        # ── Phase 2 记忆层注入 ──────────────────────────────────────────
        from engine.memory import global_topology_graph, global_episodic_memory

        # 1. 注入 L1-L7 空间拓扑图谱追溯 (Topology GraphRAG)
        affected_targets = state.get("affected_hosts", [])
        for target in affected_targets:
            topo_ctx = global_topology_graph.get_summary_context(target)
            if topo_ctx:
                summary_lines.append(f"\n{topo_ctx}")

        # 2. 注入历史相似工单与故障指纹先验 (Episodic Memory)
        few_shot = global_episodic_memory.format_as_few_shot(state.get("user_message", ""), top_k=2)
        if few_shot:
            summary_lines.append(f"\n{few_shot}")

        return "\n".join(summary_lines)




# ── 实例化各 L2 专家节点 ──────────────────────────────────────────

_INFRA_PROMPT = """你是金枢 3.0 L2 动环与基础设施专家。专精于机柜热力学演算、空调预冷、UPS负载比对与个体靶点指纹预警。
【因果推理原则】：
1. 深入挖掘物理因果，切勿停留在告警表象（如高温先排查是风道短路、盲板脱落还是算力过载）。
2. 调用工具前先在思维链中形成假设并制定验证计划，优先采用只读工具查证。
3. 分析完成后，必须输出明确的趋势判断与 TTF (Time-to-Failure) 存活时间预估。"""

_CLOUD_PROMPT = """你是金枢 3.0 L2 云原生与系统专家。专精于服务器实例调度、Linux底盘排障 (du/df/rm)、OpenStack/K8s 容器管理。
【因果推理原则】：
1. 优先审视黑板总线中动环与基础设施专家抛出的物理诱因，避免忽视物理层盲目操作。
2. 提出任何重启、隔离或下线方案前，必须执行【心智副作用预演】（评估 Quorum 多数派、跨机架冗余与 SLA 冲击）。
3. 遇到高危变更指令必须声明并触发拦截审批，绝不私自越权执行。"""

_SEC_PROMPT = """你是金枢 3.0 L2 安防与合规专家。专精于门禁比对、外部人员进场风险识别以及高危配电锁的授权验证。
【因果推理原则】：
1. 对人员进场轨迹与作业工单做时空关联推演，识别未报备闯入与越界操作。
2. 保持零信任合规审计视角，向调度中心反馈防范与复核建议。"""


infra_worker_obj = LangGraphWorkerNode(
    agent_id="L2_Infra",
    name="L2 动环专家",
    system_prompt=_INFRA_PROMPT,
    allowed_tools=[
        "query_infrastructure",
        "analyze_cooling",
        "analyze_dynamic_baseline",
        "predict_load_by_traffic",
        "fingerprint_early_warning",
        "visualize_topology",
        "analyze_thermal_infrared_matrix",
    ]
)

cloud_worker_obj = LangGraphWorkerNode(
    agent_id="L2_Cloud",
    name="L2 云原生专家",
    system_prompt=_CLOUD_PROMPT,
    allowed_tools=[
        "query_infrastructure",
        "resolve_spatial_topology",
        "execute_remote_command",
        "restart_server",
        "record_expert_experience",
    ]
)

sec_worker_obj = LangGraphWorkerNode(
    agent_id="L2_Sec",
    name="L2 安防专家",
    system_prompt=_SEC_PROMPT,
    allowed_tools=[
        "analyze_security",
        "query_infrastructure",
        "inspect_visual_patrol_frame",
    ]
)


# ── 导出为图节点函数 ──────────────────────────────────────────────

async def infra_worker_node(state: JinShuState) -> dict:
    return await infra_worker_obj.run(state)

async def cloud_worker_node(state: JinShuState) -> dict:
    return await cloud_worker_obj.run(state)

async def sec_worker_node(state: JinShuState) -> dict:
    return await sec_worker_obj.run(state)


def make_worker_node(agent_id: str):
    """根据 agent_id 返回对应的节点函数"""
    if agent_id == "L2_Infra":
        return infra_worker_node
    elif agent_id == "L2_Cloud":
        return cloud_worker_node
    elif agent_id == "L2_Sec":
        return sec_worker_node
    raise ValueError(f"Unknown agent_id: {agent_id}")
