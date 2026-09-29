# 金枢 2.0 (Jin-Shu OS) - 后向反馈、传感器与验证规范 (Feedback & Sensor Specs)

本规范定义了 Harness 作为“电子总督（Cybernetic Governor）”，如何利用确定性的反馈机制与防欺诈网关，防止大模型幻觉、说谎并建立高安全水位的物理熔断机制。

---

## 1. 编译、静态分析与确定性传感器 (Sensors & Error Mapping)

智能体在排障时，往往会尝试生成或执行 Linux CLI 脚本及 Python 探针。Harness 对此进行严格的静态分析拦截与报错提示词标准化。

```
                    +-----------------------------+
                    |  Agent Proposed Code Block  |
                    +--------------+--------------+
                                   |
                                   v
                    +-----------------------------+
                    |  Semgrep / AST static scan  |
                    +--------------+--------------+
                                   | (Violation / Error)
                                   v
                    +-----------------------------+
                    |  Standardized Error Prompt  |
                    |      (Refining Loop)        |
                    +-----------------------------+
```

### 1.1 错误映射与标准化提示 (AST Feedback Loop)
当 Agent 尝试执行代码时，Harness 的沙箱编译器会自动捕获 Traceback 并重构为 Agent 友好型 Prompt：
* **解析器错误 (ParserError)**：转换为：`"语法分析失败，错误位于第 L 行第 C 列附近，请重新编写语法结构，避免使用未定义的变量。"`
* **越权访问错误 (PermissionDenied)**：转换为：`"错误：所提代码尝试访问隔离区外的系统资源（如 /etc/shadow），违反零信任安全原则，请更换探针工具。"`

---

## 2. 动作空间验证与防欺诈网关 (Anti-Fraud & Output Gate Spec)

大模型在面临排障失败或系统拦截时，为了“满足用户期望”，经常会产生“幻觉成功”或“谎报成功”的现象（例如：宣称已通过命令清理了磁盘，但实际没有调用任何工具）。

### 2.1 防欺诈硬校验机制 (State Double-Check)
Harness 设立双向状态校验网关（Grounding Verification Gate）：

```
[Agent Response: "我已成功清理磁盘"] 
         │
         ▼ (Harness Gate Intercepts)
[Execute Deterministic Sensor: "df -h"]
         │
         ├──► (True: Space decreased) ──► Mark Passed
         │
         └──► (False: No change) ──────► Reject & Inject: "欺诈检测失败。检测到您未实际调用清理工具，磁盘空间未发生任何改变。请调用真正的命令进行处理。"
```

* **门禁动作校验**：若 Agent 输出“已锁定门禁”，网关会物理查询模拟 CMDB 中对应门禁锁的状态字。
* **虚拟机状态校验**：若 Agent 宣称“已成功将虚机热迁移”，网关会通过 OpenStack Provider API 查询物理机节点的虚拟机 UUID 队列是否已完成交割。

---

## 3. 安全合规与动态熔断机制 (Guardrails & Circuit Breaker)

### 3.1 动态熔断策略 (Circuit Breakers)
* **最大推理步数熔断 (Max Iterations Gate)**：单次排障对局中，单个 Agent 执行的 ReAct 循环次数被限制为最大 **4 次**。达到 4 次仍未输出结论时，触发硬熔断。
* **单次对局 Token / 费用熔断 (Budget Gate)**：单次排障最高允许消耗 10,000 Tokens。一旦超出，立即抛出 `CostBudgetExceeded` 异常并挂起执行。
* **高危动作熔断 (Approval Gate - HITL)**：
  * 遇到 `restart_server`、`execute_remote_command` 等 `DANGER` 级操作时，必须触发 `ApprovalRequired` 异常，中断 Agent 推理流。
  * Harness 保持会话上下文挂载，直到接收到外部 API POST `/api/chat/action` 的 `approved=True` 授权，方可热加载状态并继续执行。
