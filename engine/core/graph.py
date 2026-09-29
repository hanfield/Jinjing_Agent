r"""
金枢 3.0 - LangGraph 状态图组装 (StateGraph Definition)
=========================================================
定义图的结构、边、节点路由及内存检查点，编译生成最终的可执行图实例。

图结构：
                      [guardrail]
                           │
                 (route_after_guardrail)
                   /               \
                  ▼                 ▼
             [supervisor]        [__end__] (拦截阻断)
                  │
          (route_to_workers)
           /      │       \      \
          ▼       ▼        ▼      ▼
    [infra]    [cloud]   [sec] [summarizer]
       │          │        │
       └─────┬────┴────────┘
             ▼
      (route_after_worker)
      /                  \
     ▼                    ▼
[approval_gate]     [summarizer]
     │                    │
(route_after_appr)        ▼
     │                 [__end__]
     ▼
[worker_re_entry] (L2_Infra/Cloud/Sec)
"""

from typing import Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from .state import JinShuState
from engine.nodes.guardrail import guardrail_node, route_after_guardrail
from engine.nodes.supervisor import supervisor_node, route_to_workers
from engine.nodes.worker import infra_worker_node, cloud_worker_node, sec_worker_node
from engine.nodes.summarizer import summarizer_node


# ── Human-in-the-Loop 中断拦截门与路由函数 ───────────────────────────

async def approval_gate_node(state: JinShuState) -> dict:
    """
    审批拦截门（占位节点）。
    图运行到此处时，由于配置了 interrupt_before，LangGraph 会自动在此挂起。
    恢复运行时，此节点不修改任何状态，直接流过并计算路由。
    """
    return {}


def route_after_worker(state: JinShuState) -> Literal["approval_gate", "summarizer"]:
    """
    Worker 节点运行后的条件边。
    若 worker 需要审批，状态中 pending_approval 不为空，则分流到 approval_gate 挂起。
    否则收拢到 summarizer。
    """
    if state.get("pending_approval") is not None:
        return "approval_gate"
    return "summarizer"


def route_after_approval_gate(
    state: JinShuState,
) -> Literal["infra_worker", "cloud_worker", "sec_worker", "summarizer"]:
    """
    审批拦截门恢复运行后的条件边。
    重新跳转回发出审批请求的相应 Worker 专家节点以接续 ReAct 循环，
    或者在状态异常时流向 summarizer 兜底。
    """
    pending = state.get("pending_approval")
    if pending:
        agent_id = pending.get("agent_id")
        if agent_id == "L2_Infra":
            return "infra_worker"
        elif agent_id == "L2_Cloud":
            return "cloud_worker"
        elif agent_id == "L2_Sec":
            return "sec_worker"
    return "summarizer"


def build_graph():
    # 1. 创建基于 JinShuState 状态结构的 StateGraph
    workflow = StateGraph(JinShuState)

    # 2. 注册所有节点
    workflow.add_node("guardrail", guardrail_node)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("infra_worker", infra_worker_node)
    workflow.add_node("cloud_worker", cloud_worker_node)
    workflow.add_node("sec_worker", sec_worker_node)
    workflow.add_node("approval_gate", approval_gate_node)
    workflow.add_node("summarizer", summarizer_node)

    # 3. 设置入口边
    workflow.add_edge(START, "guardrail")

    # 4. 配置入口护栏的条件分支
    workflow.add_conditional_edges(
        "guardrail",
        route_after_guardrail,
        {
            "supervisor": "supervisor",
            "__end__": END
        }
    )

    # 5. 配置 Supervisor 任务分诊的条件路由（并发 Fan-out）
    workflow.add_conditional_edges(
        "supervisor",
        route_to_workers,
        {
            "infra_worker": "infra_worker",
            "cloud_worker": "cloud_worker",
            "sec_worker": "sec_worker",
            "summarizer": "summarizer"
        }
    )

    # 6. 配置各 Worker 专家节点的条件边（判断是否需要挂起审批）
    workflow.add_conditional_edges(
        "infra_worker",
        route_after_worker,
        {
            "approval_gate": "approval_gate",
            "summarizer": "summarizer"
        }
    )
    workflow.add_conditional_edges(
        "cloud_worker",
        route_after_worker,
        {
            "approval_gate": "approval_gate",
            "summarizer": "summarizer"
        }
    )
    workflow.add_conditional_edges(
        "sec_worker",
        route_after_worker,
        {
            "approval_gate": "approval_gate",
            "summarizer": "summarizer"
        }
    )

    # 7. 配置审批拦截门恢复后的条件边（跳转回对应 Worker 接续循环）
    workflow.add_conditional_edges(
        "approval_gate",
        route_after_approval_gate,
        {
            "infra_worker": "infra_worker",
            "cloud_worker": "cloud_worker",
            "sec_worker": "sec_worker",
            "summarizer": "summarizer"
        }
    )

    # 8. 汇总完毕后结束
    workflow.add_edge("summarizer", END)

    # 9. 编译图，配置内存检查点和审批门前置拦截（实现零编码 Session 挂起与恢复）
    memory = MemorySaver()
    compiled_graph = workflow.compile(
        checkpointer=memory,
        interrupt_before=["approval_gate"]
    )

    return compiled_graph


# 全局单例编译图
jinshu_graph = build_graph()
