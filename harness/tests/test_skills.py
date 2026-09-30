import pytest
from engine.skills import (
    global_skill_registry,
    thermal_remediation_skill,
    blast_radius_safety_skill,
    incident_postmortem_skill,
    SkillStatus,
)


def test_skill_registry():
    skills = global_skill_registry.list_skills()
    skill_names = [s["name"] for s in skills]
    assert "thermal_anomaly_remediation" in skill_names
    assert "safe_remediation_blast_radius" in skill_names
    assert "incident_postmortem_synthesis" in skill_names

    skill = global_skill_registry.get_skill("thermal_anomaly_remediation")
    assert skill is not None
    assert skill.domain == "INFRA"


@pytest.mark.asyncio
async def test_thermal_anomaly_remediation_skill():
    res = await thermal_remediation_skill.execute(rack_id="RACK-A02", height_layers=6)
    assert res.status == SkillStatus.SUCCESS
    assert len(res.steps_executed) >= 3
    assert "thermal_matrix_report" in res.findings
    assert "root_cause_hypothesis" in res.findings
    assert "codeact_optimization" in res.findings
    assert "机房热场闭环治理 SOP" in res.remediation_sop
    assert "动环热场治理技能推演报告" in res.report_markdown


@pytest.mark.asyncio
async def test_blast_radius_safety_skill():
    # SVR-001 承载 Tier-1 金融业务，应被安全护栏挂起拦截
    res = await blast_radius_safety_skill.execute(target_id="SVR-001", action="reboot")
    assert res.status == SkillStatus.PARTIAL
    assert "blast_radius" in res.findings
    assert res.findings["blast_radius"]["risk_tier"] == "HIGH"
    assert "拦截挂起" in res.remediation_sop


@pytest.mark.asyncio
async def test_incident_postmortem_skill():
    res = await incident_postmortem_skill.execute(
        incident_title="A区核心交易机柜热分层导致服务器降频告警",
        root_cause="机柜高层假盲板脱落引发冷通道风道短路",
        affected_entities=["RACK-A02", "SVR-001"],
        duration_minutes=15,
    )
    assert res.status == SkillStatus.SUCCESS
    assert "playbook_yaml" in res.findings
    assert "Remediation for Thermal Stratification" in res.findings["playbook_yaml"]
    assert "事故分析复盘报告" in res.report_markdown
    assert "Root Cause Analysis" in res.report_markdown
