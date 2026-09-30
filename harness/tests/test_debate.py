from engine.nodes.debate import should_enter_debate
from engine.core.state import make_initial_state, EvidenceItem


def test_should_enter_debate_condition():
    state = make_initial_state("测试告警")

    # 1. 只有单个专家介入时，不触发辩论
    state["evidence_chain"].append(EvidenceItem(
        source_agent="L2_Infra",
        affected_target="RACK-A02",
        ttf_minutes=15,
        confidence=0.9,
        risk_summary="机柜局部过热",
        timestamp=1000.0
    ))
    assert should_enter_debate(state) is False

    # 2. 动环和云原生专家同时介入并给出证据链时，触发辩论
    state["evidence_chain"].append(EvidenceItem(
        source_agent="L2_Cloud",
        affected_target="SVR-001",
        ttf_minutes=20,
        confidence=0.85,
        risk_summary="CPU负载高，SLA面临违约",
        timestamp=1005.0
    ))
    assert should_enter_debate(state) is True
