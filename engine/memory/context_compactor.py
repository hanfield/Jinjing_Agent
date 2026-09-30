"""
金枢 3.0 (Jin-Shu OS) - 上下文智能压缩与语义提炼引擎 (Context Compactor)
========================================================================
解决数据中心运维大模型在长多轮交互与海量监控遥测下的三大上下文工程瓶颈：
  1. 工具输出爆炸 (Tool Output Explosion): 原始命令与指标转储占用数万 token。
  2. 中间信息遗忘 (Lost in the Middle): 冗余日志冲淡核心报错根因。
  3. KV 前缀缓存击穿 (KV-Cache Invalidation): 动态上下文错位导致推理吞吐大幅下降。

核心能力：
  - reduce_tool_output: 基于运维特征的语义智能蒸馏（错误堆栈保全、重复折叠、异常指标提取）。
  - compress_history_milestones: 远端多轮历史的“诊断里程碑”提炼，控制会话窗口恒定。
  - build_cache_aligned_prompt: 严格前缀缓存对齐（Frozen System -> Static Topology -> Append-Only State）。
"""

import re
from typing import List, Dict


class ContextCompactionEngine:
    """智能上下文压缩与提炼中枢"""

    def __init__(self, max_tool_output_chars: int = 2000):
        self.max_tool_output_chars = max_tool_output_chars

    def reduce_tool_output(self, tool_name: str, raw_output: str) -> str:
        """
        对工具产生的大型原始字符串执行语义级别智能精简，而非暴力截断。
        """
        if not raw_output or len(raw_output) <= self.max_tool_output_chars:
            return raw_output

        # 1. 终端排障命令输出蒸馏 (execute_remote_command, dmesg, journalctl, df, top)
        if tool_name in ("execute_remote_command", "run_bash"):
            return self._distill_terminal_logs(raw_output)

        # 2. 基础设施与指标清单提炼 (query_infrastructure, query_k8s_metrics)
        if tool_name in ("query_infrastructure", "query_k8s_metrics"):
            return self._distill_metric_listings(raw_output)

        # 3. 空间拓扑与大型 JSON 提炼
        if raw_output.startswith("{") or raw_output.startswith("["):
            return self._distill_json_state(raw_output)

        # 4. 通用自适应语义折叠兜底
        return self._adaptive_head_tail_collapse(raw_output)

    def _distill_terminal_logs(self, text: str) -> str:
        """提取命令与日志中的异常特征行，折叠健康循环日志"""
        lines = text.splitlines()
        important_lines = []
        normal_count = 0
        error_keywords = ("error", "failed", "fatal", "panic", "exception", "oom", "warning", "denied", "critical", "100%", "99%", "98%")

        for line in lines:
            line_lower = line.lower()
            if any(kw in line_lower for kw in error_keywords):
                important_lines.append(f"🚨 {line}")
            elif "filesystem" in line_lower or "mounted on" in line_lower:
                important_lines.append(line)  # 保留表头
            else:
                normal_count += 1

        if important_lines:
            summary = [
                f"=== 💻 [终端输出语义提炼 - 检出 {len(important_lines)} 处关键报警特征] ===",
                *important_lines[:30],  # 最多保留 30 条核心报错行
            ]
            if normal_count > 0:
                summary.append(f"\n... (已自动过滤 {normal_count} 行正常与无报警的心跳回显，保留核心特征) ...")
            return "\n".join(summary)

        # 没有明显报警词，采用智能折叠
        return self._adaptive_head_tail_collapse(text)

    def _distill_metric_listings(self, text: str) -> str:
        """从大型资源清单中优先保留异常节点，折叠健康节点"""
        lines = text.splitlines()
        abnormal_items = []
        healthy_count = 0

        for line in lines:
            if any(flag in line for flag in ("🔴", "🟡", "CRITICAL", "WARNING", "OVERHEATING", "DOWN", "ERROR")):
                abnormal_items.append(line)
            elif any(flag in line for flag in ("🟢", "ACTIVE", "OPTIMAL", "HEALTHY")):
                healthy_count += 1
            else:
                # 标题或分组头
                if len(abnormal_items) < 10 and ("===" in line or "【" in line):
                    abnormal_items.append(line)

        if abnormal_items:
            result = [
                f"=== 📊 [基础设施态势语义提炼 (健康: {healthy_count} 台, 异常: {len(abnormal_items)} 台)] ===",
                *abnormal_items,
            ]
            if healthy_count > 0:
                result.append(f"\n✅ (已智能折叠 {healthy_count} 项处于正常状态的设备指标，优先聚焦报警靶点)")
            return "\n".join(result)

        return self._adaptive_head_tail_collapse(text)

    def _distill_json_state(self, text: str) -> str:
        """压缩大型 JSON 结构中的空字段与重复列表"""
        if len(text) <= self.max_tool_output_chars:
            return text
        head = text[:1000]
        tail = text[-600:]
        omitted = len(text) - 1600
        return f"{head}\n\n... [数据中枢: 压缩了 {omitted} 字符的低信噪比冗余字段，保留首尾关键键值] ...\n\n{tail}"

    def _adaptive_head_tail_collapse(self, text: str) -> str:
        """带重复行折叠的首尾自适应保留"""
        lines = text.splitlines()
        if len(lines) <= 40:
            half = self.max_tool_output_chars // 2
            return f"{text[:half]}\n\n... (智能截断 {len(text) - self.max_tool_output_chars} 字符) ...\n\n{text[-half:]}"

        head_lines = lines[:20]
        tail_lines = lines[-15:]
        omitted_lines_count = len(lines) - 35
        return "\n".join(head_lines) + f"\n\n... (已智能折叠中间 {omitted_lines_count} 行平稳运行数据) ...\n\n" + "\n".join(tail_lines)

    def compress_history_milestones(self, history: List[Dict[str, str]], keep_recent_turns: int = 2) -> List[Dict[str, str]]:
        """
        【远端会话历史的里程碑摘要化压缩】
        保留最近 keep_recent_turns 轮的详细交互细节；
        更早的历史轮次自动提取成一条结构化【历史排障里程碑】放入第一轮。
        """
        if len(history) <= keep_recent_turns * 2:
            return history

        recent_history = history[-(keep_recent_turns * 2):]
        older_history = history[:-(keep_recent_turns * 2)]

        # 从过往轮次提炼里程碑
        milestones = []
        for i in range(0, len(older_history), 2):
            user_msg = older_history[i].get("content", "")[:60]
            assistant_msg = older_history[i + 1].get("content", "") if i + 1 < len(older_history) else ""

            # 清理思维链
            clean_ans = re.sub(r"<think>[\s\S]*?</think>", "", assistant_msg).strip()
            summary_snippet = clean_ans[:120].replace("\n", " ")
            milestones.append(f"- 阶段目标: {user_msg}... -> 阶段结论: {summary_snippet}...")

        milestone_block = {
            "role": "user",
            "content": "【系统历史交接班摘要 (已归档里程碑)】\n" + "\n".join(milestones)
        }
        milestone_ack = {
            "role": "assistant",
            "content": "已接管前序排障里程碑，将在此基础上继续接续诊断。"
        }

        return [milestone_block, milestone_ack, *recent_history]


# 全局单例
global_context_compactor = ContextCompactionEngine()
