"""
金枢 2.0 (Jin-Shu OS) - Harness Task Registry (基准测试集注册表)
================================================================
负责解析和加载结构化的基准测试套件 (JSON/YAML 格式)，提供统一的任务查询与分发能力。
支持从外部 Snapshot URI 加载真实机房快照进行 Hydration。
"""

import os
import json
import urllib.request
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class GoldenMetrics:
    expected_tools: List[str]
    expected_experts: List[str]
    max_latency_ms: float
    max_tokens: int
    requires_approval_intercept: bool


@dataclass
class BenchmarkTask:
    task_id: str
    category: str
    user_prompt: str
    mock_env_state: Dict[str, Any]
    snapshot_uri: Optional[str]
    chaos_config: Dict[str, Any]
    golden_metrics: GoldenMetrics

    def hydrate_state(self) -> Dict[str, Any]:
        """优先从 snapshot_uri 拉取真实状态进行水合，否则回退到 mock_env_state"""
        if not self.snapshot_uri:
            return self.mock_env_state

        try:
            # 如果是本地文件系统快照
            if self.snapshot_uri.startswith("file://") or self.snapshot_uri.startswith("/"):
                path = self.snapshot_uri.replace("file://", "")
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
            # 如果是远程 HTTP 快照库
            elif self.snapshot_uri.startswith("http"):
                req = urllib.request.Request(self.snapshot_uri, headers={'User-Agent': 'JinShu-Harness/2.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            print(f"⚠️ [Data Hydration] 无法拉取快照 {self.snapshot_uri}: {e}。退回 mock_env_state。")

        return self.mock_env_state


class TaskRegistry:
    """基准任务加载与管理中心"""

    def __init__(self, config_path: str = None):
        self.tasks: Dict[str, BenchmarkTask] = {}
        self.suite_metadata: Dict[str, Any] = {}
        if config_path:
            self.load_suite(config_path)

    def load_suite(self, config_path: str):
        """加载配置文件中的评测用例"""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件未找到: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.suite_metadata = {
            "suite_name": data.get("suite_name", "Unknown_Suite"),
            "version": data.get("version", "1.0.0"),
            "description": data.get("description", ""),
            "weight_eng": data.get("weight_eng", 0.6),
            "weight_judge": data.get("weight_judge", 0.4)
        }

        for item in data.get("tasks", []):
            gm_data = item.get("golden_metrics", {})
            gm = GoldenMetrics(
                expected_tools=gm_data.get("expected_tools", []),
                expected_experts=gm_data.get("expected_experts", []),
                max_latency_ms=gm_data.get("max_latency_ms", 15000.0),
                max_tokens=gm_data.get("max_tokens", 4096),
                requires_approval_intercept=gm_data.get("requires_approval_intercept", False)
            )
            task = BenchmarkTask(
                task_id=item.get("task_id"),
                category=item.get("category", "DEFAULT"),
                user_prompt=item.get("user_prompt", ""),
                mock_env_state=item.get("mock_env_state", {}),
                snapshot_uri=item.get("snapshot_uri"),
                chaos_config=item.get("chaos_config", {}),
                golden_metrics=gm
            )
            self.tasks[task.task_id] = task

    def get_task(self, task_id: str) -> Optional[BenchmarkTask]:
        return self.tasks.get(task_id)

    def list_tasks(self) -> List[BenchmarkTask]:
        return list(self.tasks.values())
