import os
import json
from harness.tasks.task_registry import TaskRegistry, BenchmarkTask

def test_registry_loading():
    """测试 TaskRegistry 能否正确加载测试套件配置"""
    # 构造一个临时配置文件
    test_config = {
        "suite_name": "Test_Suite",
        "version": "1.0.0",
        "tasks": [
            {
                "task_id": "TEST_001",
                "category": "MOCK",
                "user_prompt": "Mock prompt",
                "mock_env_state": {},
                "golden_metrics": {
                    "expected_tools": ["mock_tool"],
                    "expected_experts": ["Mock_Agent"],
                    "max_latency_ms": 1000.0,
                    "max_tokens": 1000,
                    "requires_approval_intercept": False
                }
            }
        ]
    }

    config_path = "/tmp/test_eval.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(test_config, f)

    registry = TaskRegistry(config_path)

    assert registry.suite_metadata["suite_name"] == "Test_Suite"
    assert registry.suite_metadata["version"] == "1.0.0"

    tasks = registry.list_tasks()
    assert len(tasks) == 1

    task = registry.get_task("TEST_001")
    assert isinstance(task, BenchmarkTask)
    assert task.golden_metrics.expected_tools == ["mock_tool"]
    assert task.golden_metrics.max_latency_ms == 1000.0

    # 清理临时文件
    os.remove(config_path)
