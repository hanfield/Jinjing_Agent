# 金枢 2.0 (Jin-Shu OS) - 运行时状态、记忆与追踪规范 (Runtime State & Observability Specs)

本规范定义了金枢 2.0 运行期状态机的持久化机制、智能体记忆体分层设计、热加载策略以及全链路审计遥测系统。

---

## 1. 记忆体架构与情景记忆持久化 (Episodic Memory Design)

智能体的记忆体系分为三个层次，以确保其既能处理即时排障，又能通过历史经验进行自演进：

```
+------------------------------------------------------------------------+
|                          Memory Layering                               |
+------------------------------------------------------------------------+
| 1. 短期工作区记忆 (Short-Term Active Session Memory):                    |
|    - 存于内存中，按 ReAct 循环流转，单次排障结束后销毁。                |
+------------------------------------------------------------------------+
| 2. 情景记忆/反思经验 (Episodic Reflection Memory):                       |
|    - 调用 `record_expert_experience` 提纯为专家指纹，以 JSONL 形式持久化。 |
+------------------------------------------------------------------------+
| 3. 长期语义知识库 (Long-Term Vector / Graph DB):                        |
|    - 存储设备 SOP 静态手册与依赖树拓扑。                               |
+------------------------------------------------------------------------+
```

---

## 2. 状态热加载与故障复原机制 (State Hydration & Resiliency)

为了应对网络闪断、物理机房重启或等待人工审批时的超长等待挂起，金枢支持 **“无损状态冷冻与热加载（Hydration）”**。

```
    [Agent Waiting for Approval]
                 │
                 ▼ (Freeze State)
    ┌───────────────────────────┐
    │ serialize(Active Context)  ├──► Write to solution_history.json
    └───────────────────────────┘
                 │ (Network Reconnect / Operator Approves)
                 ▼ (Hydrate State)
    ┌───────────────────────────┐
    │ deserialize(Active Context)◄── Load Session from JSON
    └───────────────────────────┘
                 │
                 ▼
      [Resume Execution Flow]
```

### 2.1 序列化快照结构 (Serialization Schema)
当 Agent 进入挂起或中断状态时，其上下文被序列化为结构化数据并写入 `data/solution_history.json`：
* **`session_id`**：唯一对局 ID。
* **`blackboard_snapshot`**：黑板总线在中断瞬间的数据快照（动环指标、证据链、受影响虚机）。
* **`history_messages`**：包含 Supervisor 及各 Worker 的全量推理思维链与已调用的工具记录。

---

## 3. 全量审计与可观测性白皮书 (Telemetry & Telemetry Auditing)

任何一次线上故障的处理轨迹都必须可追溯、可审计。

### 3.1 推理轨迹数据结构 (Trajectory Trails Schema)
Harness 对智能体集群的每一步动作（Tool Call、思维、观测值）进行结构化追踪：

```json
{
  "trace_id": "trace-hvac-cascade-001",
  "timestamp": 1781290382.91,
  "steps": [
    {
      "step_index": 1,
      "agent_id": "L1_Supervisor",
      "action": "triage",
      "output": ["L2_Infra", "L2_Cloud"],
      "latency_ms": 1200.5
    },
    {
      "step_index": 2,
      "agent_id": "L2_Infra",
      "action": "thought",
      "content": "分析 RACK-A02 温度动态基线，判定是否存在热漏泄...",
      "latency_ms": 820.1
    },
    {
      "step_index": 3,
      "agent_id": "L2_Infra",
      "action": "tool_call",
      "name": "fingerprint_early_warning",
      "arguments": {},
      "observation": "发现靶点：RACK-A02，预计 15 分钟内崩溃"
    }
  ]
}
```

### 3.2 死后剖析指南 (Post-Mortem Auditing Guide)
当评测大盘报告 `FAILED` 时，架构师应通过审计日志定位根本成因：
1. **Tooling failure**：检查工具是否抛出了底层连接异常（如 CMDB 无法连通）。
2. **Retrieval gap**：比对 RAG 召回精度。若 `answer_faithfulness` 得分低，说明模型在没有相关 SOP 的情况下胡乱生成了处置命令。
3. **Reasoning failure**：大模型思维链发生混乱或死循环（可通过 LLM-as-a-Judge 评语定位）。
