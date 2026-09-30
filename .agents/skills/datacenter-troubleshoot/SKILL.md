---
name: datacenter-troubleshoot
description: >-
  Use this skill when diagnosing data center incidents, performing root-cause analysis across
  L1-L7 infra and cloud layers, executing hypothesis tree searches, or evaluating blast radius
  for remediations in Jin-Shu OS.
---

# 数据中心复合故障排查与智能体排障推演运维技能 (Datacenter Troubleshooting Skill)

本技能指导开发者与 AI 智能体在面对中国金电等生产数据中心的复合型模糊告警时，规范化调用金枢 (Jin-Shu OS) 3.0 的前沿推演机制进行根因闭环。

## 适用场景
- 机房出现机柜高温、局部热分层或 CRAC 精密空调排风异常；
- 宿主机硬件告警伴随上层云原生应用（K8s / OpenStack）延迟升高或掉线；
- 需对计划实施的破坏性操作（重启、隔离、关机）进行前置爆炸半径穿透评估。

## 标准排查与推演 SOP

### 1. 启动假说树搜索 (Hypothesis Tree Search / MCTS-Lite)
破除单线 ReAct 贪心试错陷阱，主动对多诱因故障发起候选因果假说裂变：
```python
from engine.nodes.hypothesis_tree import global_hypothesis_explorer

# 自动裂变 3 个物理/逻辑正交分支，并发派发只读探针并剪枝
res = global_hypothesis_explorer.explore(
    incident="A区机柜出现高温且核心结算服务处理延迟上涨",
    target="RACK-A02"
)
print(res["tree_summary"])
```

### 2. 调用 CodeAct 沙箱执行动态分析 (CodeAct Dynamic Sandbox)
当需要对非标准日志进行正则提取、或针对热力学微分方程/变频曲线进行计算时：
```python
from engine.tools.codeact_sandbox import execute_python_codeact

script = """
temps = [23.0, 23.8, 24.6, 25.4, 26.2, 27.5]
delta_t = max(temps) - min(temps)
print(f"机柜垂直温差 ΔT: {delta_t:.1f}°C")
if delta_t > 4.0:
    print("判定: 存在显著垂直热分层，需核查机柜顶层盲板与地板风口开度。")
"""
print(execute_python_codeact(script, timeout_seconds=3))
```

### 3. 前置爆炸半径与金融业务穿透 (Blast Radius Assessment)
在执行任何变更或自愈措施前，**必须**调用拓扑图谱计算下游波及业务与 Quorum 影响：
```python
from engine.memory.topology_graph import global_topology_graph

blast = global_topology_graph.calculate_blast_radius(target_id="SVR-001", action="reboot")
if blast["requires_approval"]:
    print(f"🚨 操作涉及关键业务 ({blast['critical_workloads']})，必须触发 Human-in-the-Loop 审批拦截门！")
```

### 4. 调用高阶闭环治理技能 (Composite Skills)
直接调用预制的高阶复合技能完成端到端治理：
- `thermal_remediation_skill`: 红外扫描 + 假说树 + CodeAct 计算 + 封堵 SOP
- `blast_radius_safety_skill`: 准入审计 + 仲裁风险分析
- `incident_postmortem_skill`: SRE 标准 Post-Mortem + 自动化 Playbook YAML 导出
