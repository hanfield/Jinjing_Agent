"""
金枢 2.0 (Jin-Shu OS) - 全局黑板总线与状态治理中枢 (Blackboard Pattern)
====================================================================
实现星型总线通信拓扑，彻底杜绝 Worker Agent 之间的网状直接对话，消除上下文污染与 Token 雪崩。

核心设计：
  1. 共享状态树 (IncidentState)：维护全局告警靶点、动环指标、受影响主机及审批锁。
  2. 结构化证据链投递：Worker 执行完毕后，只将经过修剪的 JSON 摘要写入黑板。
  3. 精准订阅机制：下游 Agent 仅订阅黑板中的关键参数，直接跳过冗余排查。
"""

import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class EvidenceItem:
    """单条结构化风险判定证据链"""
    source_agent: str             # 提交方，如 'L2_Infra'
    affected_target: str          # 受影响靶点，如 'RACK-A02'
    ttf_minutes: int              # 预估存活时间 (Time to Failure)
    confidence: float             # 专家判定置信度 (0.0 ~ 1.0)
    risk_summary: str             # 结构化推演摘要
    timestamp: float = field(default_factory=time.time)


class Blackboard:
    """
    全局黑板总线 (Star Topology Bus)。
    所有 L1 Supervisor 和 L2 Worker 智能体通过本总线进行解耦通信与状态共享。
    """

    def __init__(self):
        self.session_id: str = "default-incident"
        self.status: str = "NORMAL"  # NORMAL / WARNING / CRITICAL / RESOLVED
        
        # 核心状态空间
        self.environment_status: Dict[str, Any] = {}      # 动环状态，如机柜温度、UPS负载
        self.affected_hosts: List[str] = []               # 受影响的云原生主机列表
        self.security_locks: Dict[str, bool] = {}         # 安防与配电锁状态
        self.evidence_chain: List[EvidenceItem] = []      # 风险判定证据链集合
        
        # 执行与调度锁
        self.active_worker: Optional[str] = None          # 当前正在执行的专家 Agent
        self.approval_pending: bool = False               # 是否有高危操作正在等待主管审批
        self.pending_tool_call: Optional[Dict[str, Any]] = None

    def reset(self, session_id: str = "default-incident"):
        """重置黑板状态，开启新排障对局"""
        self.__init__()
        self.session_id = session_id

    def update_environment(self, rack_id: str, temp: float, load_ratio: float):
        """动环专家写入环境指标"""
        self.environment_status[rack_id] = {
            "temp_celsius": temp,
            "load_ratio": load_ratio,
            "updated_at": time.time()
        }
        if temp > 30.0 or load_ratio > 0.85:
            self.status = "CRITICAL"

    def add_affected_hosts(self, hosts: List[str]):
        """云原生专家写入受影响主机"""
        for h in hosts:
            if h not in self.affected_hosts:
                self.affected_hosts.append(h)

    def set_security_lock(self, device_id: str, locked: bool):
        """安防专家修改物理/逻辑门禁与配电锁"""
        self.security_locks[device_id] = locked

    def post_evidence(self, item: EvidenceItem):
        """投递经过修剪与提纯的结构化证据链（防上下文污染核心）"""
        self.evidence_chain.append(item)
        if item.ttf_minutes <= 15 and item.confidence > 0.8:
            self.status = "CRITICAL"

    def get_context_summary(self, target_agent: str) -> str:
        """
        [上下文修剪引擎 Context Pruning Engine]：
        根据目标下游 Agent 的角色，按需提取精简黑板摘要，拒绝发送全量历史对话。
        """
        summary_lines = [f"### 📋 全局黑板状态总线摘要 (当前态势: {self.status})"]
        
        if target_agent == "L2_Cloud":
            # 云原生专家仅需关注受影响的主机与底层物理诱因
            summary_lines.append("#### 🖥️ 云原生与主机态势订阅")
            summary_lines.append(f"- 受影响主机队列: {', '.join(self.affected_hosts) if self.affected_hosts else '暂无直接受影响主机'}")
            # 提取动环抛出的物理红线证据
            infra_ev = [e for e in self.evidence_chain if e.source_agent == "L2_Infra"]
            for ev in infra_ev:
                summary_lines.append(f"- ⚠️ [底层动环诱因]: 靶点 {ev.affected_target} 预计 {ev.ttf_minutes} 分钟内崩溃 ({ev.risk_summary})")
                
        elif target_agent == "L2_Infra":
            # 动环专家关注环境热点与机柜功耗
            summary_lines.append("#### 🗄️ 动环与基础设施态势订阅")
            summary_lines.append(f"- 环境遥测快照: {json.dumps(self.environment_status, ensure_ascii=False)}")
            
        elif target_agent == "L2_Sec":
            # 安防专家关注高危拦截与门禁配电锁
            summary_lines.append("#### 🔒 安防与合规态势订阅")
            summary_lines.append(f"- 物理/逻辑锁状态: {json.dumps(self.security_locks, ensure_ascii=False)}")
            summary_lines.append(f"- 待审批拦截流: {'开启' if self.approval_pending else '无'}")

        # 附加最新的顶级置信度证据
        if self.evidence_chain:
            top_ev = sorted(self.evidence_chain, key=lambda x: x.confidence, reverse=True)[0]
            summary_lines.append(f"\n#### 🏆 全局最高置信度判定: [{top_ev.source_agent}] -> {top_ev.risk_summary}")

        return "\n".join(summary_lines)

    def export_snapshot(self) -> Dict[str, Any]:
        """导出全局黑板快照，供沙箱仿真 (Harness) 与前端大屏渲染使用"""
        return {
            "session_id": self.session_id,
            "status": self.status,
            "environment_status": self.environment_status,
            "affected_hosts": self.affected_hosts,
            "security_locks": self.security_locks,
            "evidence_count": len(self.evidence_chain),
            "approval_pending": self.approval_pending
        }


# 全局单例黑板总线
global_blackboard = Blackboard()
