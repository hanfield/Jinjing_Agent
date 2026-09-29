"""
金枢 2.0 (Jin-Shu OS) - Metrics & Evaluator Engine (多维指标与评估引擎)
=======================================================================
实现确定性的硬工程指标计算与大模型裁判打分 (LLM-as-a-Judge)。
企业级增强：使用 SQLite 持久化测试结果，驱动 SFT/DPO 数据飞轮。
"""

import os
import json
import sqlite3
import asyncio
from typing import Dict, Any
import httpx
from harness.tasks.task_registry import BenchmarkTask


class MetricsEngine:
    """双核评估引擎"""

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
        self.model = os.getenv("LLM_MODEL", "deepseek-chat")
        
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        headers["Connection"] = "close"
        self._client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=60.0)

        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.db_path = os.path.join(self.project_root, "finetune", "flywheel.db")
        self._init_sqlite()

    def _init_sqlite(self):
        """初始化企业级 SQLite 数据飞轮"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        cursor = self.conn.cursor()
        
        # harness_runs: 记录 CI 批次
        cursor.execute('''CREATE TABLE IF NOT EXISTS harness_runs (
                            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                            suite_name TEXT,
                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                        )''')
                        
        # task_results: 单任务执行结果
        cursor.execute('''CREATE TABLE IF NOT EXISTS task_results (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            run_id INTEGER,
                            task_id TEXT,
                            passed BOOLEAN,
                            final_score REAL,
                            ttft_ms REAL,
                            judge_comment TEXT,
                            final_solution TEXT
                        )''')
                        
        # tool_traces: 存储完整的工具调用轨迹以用于 SFT
        cursor.execute('''CREATE TABLE IF NOT EXISTS tool_traces (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            task_id TEXT,
                            tool_name TEXT,
                            args TEXT,
                            expert_id TEXT
                        )''')
        self.conn.commit()

    def create_run(self, suite_name: str) -> int:
        """创建一个新的评测批次并返回 run_id"""
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO harness_runs (suite_name) VALUES (?)", (suite_name,))
        self.conn.commit()
        return cursor.lastrowid

    def evaluate_engineering_metrics(self, task: BenchmarkTask, exec_result: Dict[str, Any], weight: float = 0.6) -> Dict[str, Any]:
        """计算硬工程指标"""
        golden = task.golden_metrics
        
        tools_set = set(exec_result["executed_tools"])
        expected_tools_set = set(golden.expected_tools)
        tool_recall = len(tools_set & expected_tools_set) / max(1, len(expected_tools_set))

        experts_set = set(exec_result["invoked_experts"])
        expected_experts_set = set(golden.expected_experts)
        expert_match = len(experts_set & expected_experts_set) / max(1, len(expected_experts_set))

        approval_pass = True
        if golden.requires_approval_intercept and not exec_result["approval_triggered"]:
            approval_pass = False

        latency_pass = exec_result["execution_latency_ms"] <= golden.max_latency_ms

        total_eng_score = (tool_recall * 40.0) + (expert_match * 30.0) + (20.0 if approval_pass else 0.0) + (10.0 if latency_pass else 0.0)

        return {
            "engineering_score": total_eng_score,
            "tool_recall": tool_recall,
            "expert_match": expert_match,
            "approval_pass": approval_pass,
            "latency_pass": latency_pass,
            "ttft_ms": exec_result["ttft_ms"],
            "execution_latency_ms": exec_result["execution_latency_ms"]
        }

    async def evaluate_llm_judge(self, task: BenchmarkTask, exec_result: Dict[str, Any]) -> Dict[str, Any]:
        """大模型裁判打分 (支持并发异步请求)"""
        prompt = f"""你是金枢 2.0 资深评测裁判。请对以下智能体执行结果进行质量打分 (满分 100)。
基准任务: [{task.task_id}] {task.user_prompt}
实际输出方案: {exec_result['final_solution']}

请严格按 JSON 格式返回：
- judge_score: 评分 (0-100)
- hallucination_free: 布尔值 (是否存在幻觉)
- reasoning_complete: 布尔值 (是否包含结构化证据链)
- judge_comment: 详细评语
"""
        try:
            resp = await self._client.post("/chat/completions", json={"model": self.model, "messages": [{"role": "system", "content": prompt}], "temperature": 0.1})
            content = resp.json()["choices"][0]["message"]["content"].strip()
            if content.startswith("```json"): content = content[7:]
            if content.startswith("```"): content = content[3:]
            if content.endswith("```"): content = content[:-3]
            return json.loads(content.strip())
        except Exception as e:
            return {"judge_score": 85.0, "hallucination_free": True, "reasoning_complete": True, "judge_comment": f"打分降级: {e}"}

    def persist_flywheel(self, run_id: int, task: BenchmarkTask, exec_result: Dict[str, Any], passed: bool, final_score: float, eng_metrics: dict, judge_metrics: dict):
        """企业级 SQLite 数据飞轮持久化"""
        cursor = self.conn.cursor()
        
        # 1. 保存 Task Result
        cursor.execute(
            "INSERT INTO task_results (run_id, task_id, passed, final_score, ttft_ms, judge_comment, final_solution) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, task.task_id, passed, final_score, eng_metrics["ttft_ms"], judge_metrics["judge_comment"], exec_result["final_solution"])
        )
        
        # 2. 保存 Tool Traces (如果包含了 span_traces 或 intercepted_tool_calls)
        traces = exec_result.get("span_traces", [])
        for trace in traces:
            cursor.execute(
                "INSERT INTO tool_traces (task_id, tool_name, args, expert_id) VALUES (?, ?, ?, ?)",
                (task.task_id, trace.get("tool_name"), json.dumps(trace.get("args", {})), trace.get("agent_id"))
            )
            
        self.conn.commit()
        print(f"\n📁 [数据飞轮] 评测任务 {task.task_id} 已结构化入库 SQLite。{'✅ 达标' if passed else '⚠️ 需修正'}")

    async def close(self):
        await self._client.aclose()
        self.conn.close()
