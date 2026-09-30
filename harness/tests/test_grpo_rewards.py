from finetune.train_grpo import (
    reasoning_structure_reward,
    root_cause_accuracy_reward,
    safety_constraint_reward,
    sop_actionable_reward,
    compute_combined_rewards,
    compute_group_relative_advantages,
)


def test_reasoning_structure_reward():
    # 1. 具备完整闭合长思维链与结论
    good_completion = "<think>排查 A02 机柜温度升高，验证物理根因为冷凝水管破裂，需前置申请审批后迁移。</think>【结论】请按应急预案执行备用空调倒换。"
    scores = reasoning_structure_reward([good_completion])
    assert scores[0] >= 1.0

    # 2. 未闭合标签应受惩罚
    unclosed_completion = "<think>正在排查中..."
    scores_bad = reasoning_structure_reward([unclosed_completion])
    assert scores_bad[0] < 0.0

    # 3. 缺乏思维链
    no_think = "直接重启服务器"
    scores_none = reasoning_structure_reward([no_think])
    assert scores_none[0] < 0.0


def test_root_cause_accuracy_reward():
    gt = ["冷凝水,CRAC-A01,排水管"]
    hit_completion = ["根据现场反馈，确认是 CRAC-A01 排水管渗漏冷凝水导致的动环警报。"]
    miss_completion = ["认为是黑客入侵导致的 CPU 算力打满。"]

    hit_score = root_cause_accuracy_reward(hit_completion, ground_truth=gt)
    miss_score = root_cause_accuracy_reward(miss_completion, ground_truth=gt)

    assert hit_score[0] > 1.5
    assert miss_score[0] == 0.0


def test_safety_constraint_reward():
    # 包含高危操作，但有审批和 Quorum/SLA 冲击校验
    safe_danger = ["提议执行 restart_server 重启，操作前需提交值班主管审批，并预估 Quorum 多数派与下游 SLA 冲击。"]
    # 包含高危操作，但属于私自直接执行
    reckless_danger = ["我立即执行 restart_server 下线主机。"]
    # 纯只读操作
    read_only = ["查询当前空调出风温度与母线电压。"]

    safe_score = safety_constraint_reward(safe_danger)
    reckless_score = safety_constraint_reward(reckless_danger)
    read_score = safety_constraint_reward(read_only)

    assert safe_score[0] >= 1.0
    assert reckless_score[0] < 0.0
    assert read_score[0] > 0.0


def test_sop_actionable_reward():
    sop_text = ["【应急处置 SOP】\n步骤 1. 使用 df -h 查看磁盘\n步骤 2. 执行恢复验证"]
    score = sop_actionable_reward(sop_text)
    assert score[0] >= 1.0


def test_compute_combined_rewards():
    res = compute_combined_rewards(["<think>排查...</think>【处置建议】1. 检查"], ground_truth=["排查"])
    assert "total_reward" in res
    assert len(res["total_reward"]) == 1


def test_group_relative_advantage():
    rewards = [5.0, 1.0]
    advs = compute_group_relative_advantages(rewards)
    assert len(advs) == 2
    # 优势高的应该为正，低的为负，均值接近 0
    assert advs[0] > 0
    assert advs[1] < 0
    assert abs(advs[0] + advs[1]) < 0.01

