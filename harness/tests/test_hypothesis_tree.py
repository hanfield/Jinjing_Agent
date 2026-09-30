import pytest
from engine.nodes.hypothesis_tree import HypothesisTreeExplorer


@pytest.mark.asyncio
async def test_hypothesis_tree_workflow():
    explorer = HypothesisTreeExplorer()

    # 1. 裂变候选假说
    candidates = explorer.generate_candidate_hypotheses("SVR-001 温度升高且响应延迟", target="SVR-001")
    assert len(candidates) == 3
    assert any(c.hypothesis_id == "H_INFRA" for c in candidates)
    assert any(c.hypothesis_id == "H_CLOUD" for c in candidates)
    assert any(c.hypothesis_id == "H_POWER" for c in candidates)

    # 2. 并发执行探针
    probed = await explorer.execute_parallel_probes(candidates)
    assert len(probed) == 3
    # 探针应当获取到了真实或仿真证据
    for b in probed:
        assert len(b.evidence_finding) > 0

    # 3. 证据打分与剪枝判定
    eval_result = explorer.evaluate_and_prune(probed)
    assert "winning_hypothesis" in eval_result
    assert "pruned_branches" in eval_result
    assert "tree_summary" in eval_result

    winner = eval_result["winning_hypothesis"]
    assert winner.confidence_score > 0.5
    assert "假说树搜索推演报告" in eval_result["tree_summary"]
    assert "胜出真因路径" in eval_result["tree_summary"]
    assert "剪除证伪分支" in eval_result["tree_summary"]


def test_hypothesis_tree_tool():
    from engine.tools import registry
    tool = registry.get_tool("explore_hypothesis_tree")
    assert tool is not None
    assert tool.risk_level.value == "safe"

    report = tool.fn(incident="机架A02温升突发且服务响应迟缓", target="SVR-001")
    assert "假说树搜索推演报告" in report
    assert "胜出真因路径" in report
    assert "剪除证伪分支" in report
