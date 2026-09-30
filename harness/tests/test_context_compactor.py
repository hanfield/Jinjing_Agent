from engine.memory.context_compactor import ContextCompactionEngine


def test_terminal_log_distillation():
    engine = ContextCompactionEngine(max_tool_output_chars=300)
    # 模拟包含 100 行常规系统日志与 2 行致命错误的输出
    logs = ["Apr 10 10:00:01 kernel: normal heartbeat tick"] * 80
    logs.append("Apr 10 10:00:05 kernel: [ERROR] Out of memory: Kill process 1234 (mysqld)")
    logs.extend(["Apr 10 10:00:06 kernel: normal heartbeat tick"] * 20)
    logs.append("Apr 10 10:00:09 kernel: [FATAL] Kernel panic - not syncing: VFS: Unable to mount root fs")

    raw_output = "\n".join(logs)
    distilled = engine.reduce_tool_output("execute_remote_command", raw_output)

    assert "终端输出语义提炼" in distilled
    assert "Out of memory" in distilled
    assert "Kernel panic" in distilled
    assert "已自动过滤" in distilled
    assert len(distilled) < len(raw_output)


def test_metric_listing_distillation():
    engine = ContextCompactionEngine(max_tool_output_chars=400)
    # 模拟 30 台正常物理机与 1 台高温告警机柜
    lines = ["=== 机房基础设施清单 ==="]
    for i in range(1, 31):
        lines.append(f"🟢 SVR-{i:03d} | 状态: ACTIVE | 温度: 24.0°C | 负载: 45%")
    lines.append("🔴 RACK-A02 | 状态: OVERHEATING | 温度: 34.5°C | 局部严重过热")

    raw_output = "\n".join(lines)
    distilled = engine.reduce_tool_output("query_infrastructure", raw_output)

    assert "基础设施态势语义提炼" in distilled
    assert "RACK-A02" in distilled
    assert "OVERHEATING" in distilled
    assert "已智能折叠" in distilled


def test_milestone_history_compaction():
    engine = ContextCompactionEngine()
    # 构造一个 6 轮交互的历史记录
    history = [
        {"role": "user", "content": "帮我看看机柜 A01 为什么警报"},
        {"role": "assistant", "content": "<think>推演中...</think>排查发现是风道由于线缆堆叠受阻，已生成吹扫任务。"},
        {"role": "user", "content": "检查一下备用 UPS 电压"},
        {"role": "assistant", "content": "<think>推演中...</think>UPS-A01 电压处于 380V 正常区间。"},
        {"role": "user", "content": "把最新的门禁记录调出来"},
        {"role": "assistant", "content": "近两小时外部人员无越界刷卡。"},
    ]

    compressed = engine.compress_history_milestones(history, keep_recent_turns=1)
    # 应被压缩为：1 条归档里程碑 + 1 条助理确认 + 最近 1 轮问答（2条） = 4 条
    assert len(compressed) == 4
    assert "系统历史交接班摘要 (已归档里程碑)" in compressed[0]["content"]
    assert "把最新的门禁记录调出来" in compressed[2]["content"]
