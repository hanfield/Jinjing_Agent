---
name: grpo-agent-finetuning
description: >-
  Use this skill when training, evaluating, or fine-tuning Jin-Shu OS agents using Group
  Relative Policy Optimization (GRPO/RLVR), designing multi-objective reward models, or
  preparing DPO/SFT training data.
---

# 基于 GRPO/RLVR 的智能体强化学习微调技能 (GRPO Agent Fine-Tuning Skill)

本技能指导开发者基于 DeepSeek-R1 开创的 Group Relative Policy Optimization (GRPO) 强化学习范式，对数据中心智能体进行长思维链与可验证奖励（RLVR）后训练。

## 适用场景
- 训练具备机房自主因果排查能力的长思维链专用模型（如 Qwen2.5-7B/32B-Instruct）；
- 替代传统依赖 Critic 价值模型的 PPO 架构，节省 50% 显存；
- 定制机房特定奖励函数（动环指标准确度、安全合规性、可执行 SOP 奖励）。

## 核心工作流与操作规程

### 1. 规则驱动的多目标复合奖励设计 (Multi-Objective Rewards)
GRPO 依赖确定性、免评判模型的规则校验奖励组合（见 `finetune/train_grpo.py`）：
- `reasoning_structure_reward`: 校验 `<think>...</think>` 闭合性与思维链展开度（权重 0.20）；
- `root_cause_accuracy_reward`: 校验是否精准锁定真因资产与诱因（权重 0.40）；
- `safety_constraint_reward`: 严重惩罚未经审批即发起关机、隔离高危操作（权重 0.25）；
- `sop_actionable_reward`: 检查是否生成了包含操作对象、参数与验证步骤的完整 SOP（权重 0.15）。

### 2. 组内相对优势计算 (Group Relative Advantage)
针对同一告警 prompt，并行采样 $G$ 条完成候选（Completion），计算无 Critic 模型的优势归一化：
$$A_i = \frac{R_i - \text{mean}(R)}{\text{std}(R) + \epsilon}$$

### 3. 运行微调训练
```bash
# 1. 准备训练集
python finetune/prepare_data.py

# 2. 运行 GRPO 规则强化学习训练 (DeepSpeed ZeRO-3)
deepspeed finetune/train_grpo.py --deepspeed finetune/ds_config.json

# 3. macOS 本地验证 (MLX LoRA 轻量微调)
python finetune/train_mlx_lora.py
```

### 4. 验证奖励与优势分布
运行回归测试以核验奖励函数对长思维链、未闭合思维及违规动作的判别准确性：
```bash
pytest harness/tests/test_grpo_rewards.py
```
