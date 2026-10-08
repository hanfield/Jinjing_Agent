import pytest
from engine.core.datacenter_adapter import (
    SemanticPointMatcher,
    global_datacenter_manager,
    SafetyPolicyLevel,
)
from engine.skills.thermal_remediation_skill import thermal_remediation_skill


def test_semantic_point_matcher_vendor_normalization():
    """测试多厂商异构遥测点位免驱动智能自动归一化"""
    # 模拟华为、维谛与传统动环上报的混乱字段名
    messy_vendor_telemetry = {
        "Huawei_CRAC01_回风温度": 26.8,
        "Vertiv_Supply_Temp": 18.2,
        "机房风机频率_Hz": 46.5,
        "UPS_B_Battery_SOC": 98.0,
        "Unrecognized_Custom_Sensor": "OK"
    }

    canonical = SemanticPointMatcher.canonicalize_telemetry(messy_vendor_telemetry)

    # 验证关键物理量槽位被精准提取
    assert "return_temp" in canonical
    assert canonical["return_temp"] == 26.8

    assert "supply_temp" in canonical
    assert canonical["supply_temp"] == 18.2

    assert "fan_speed_hz" in canonical
    assert canonical["fan_speed_hz"] == 46.5

    assert "battery_percent" in canonical
    assert canonical["battery_percent"] == 98.0

    # 未知字段安全透传
    assert canonical["Unrecognized_Custom_Sensor"] == "OK"


def test_yaml_profile_hydration():
    """测试仅通过极简 YAML 声明即可在秒级水合异构机房画像与拓扑"""
    bj_ctx = global_datacenter_manager.load_from_yaml("data/profiles/beijing_core_tier4.yaml")
    assert bj_ctx.profile.datacenter_id == "DC-BEIJING-FIN-01"
    assert bj_ctx.profile.safety_policy == SafetyPolicyLevel.STRICT_HITL
    assert bj_ctx.profile.thermodynamics.target_temp_celsius == 23.5
    assert "BJ-RACK-01" in bj_ctx.profile.racks

    sz_ctx = global_datacenter_manager.load_from_yaml("data/profiles/shenzhen_edge_modular.yaml")
    assert sz_ctx.profile.datacenter_id == "DC-SHENZHEN-EDGE-02"
    assert sz_ctx.profile.safety_policy == SafetyPolicyLevel.AUTONOMOUS_OPTIMIZE
    assert sz_ctx.profile.thermodynamics.target_temp_celsius == 25.0
    assert "INROW-SZ-01" in sz_ctx.profile.coolers


def test_relative_topological_cooler_lookup():
    """测试相对拓扑寻址：通过空间图谱自动定位负责制冷源，彻底告别设备名写死"""
    bj_ctx = global_datacenter_manager.get_context("DC-BEIJING-FIN-01")
    # 针对 BJ-RACK-01 自动寻址出北京机房的空调 CRAC-BJ-01/02
    coolers = bj_ctx.find_associated_coolers("BJ-RACK-01")
    assert any("CRAC-BJ" in c for c in coolers)

    sz_ctx = global_datacenter_manager.get_context("DC-SHENZHEN-EDGE-02")
    sz_coolers = sz_ctx.find_associated_coolers("SZ-GPU-RACK-01")
    assert "INROW-SZ-01" in sz_coolers


@pytest.mark.asyncio
async def test_thermal_skill_cross_datacenter_plug_and_play():
    """
    终极验证：同一套 Thermal Remediation Skill 代码，零修改直接即插即用在
    北京金融核心机房 (Tier-4, 强制审批) 与 深圳边缘微模块机房 (Tier-2, 自主放行)
    """
    # 场景 1: 在北京金融生产中心运行
    bj_ctx = global_datacenter_manager.get_context("DC-BEIJING-FIN-01")
    res_bj = await thermal_remediation_skill.execute(
        rack_id="BJ-RACK-01",
        datacenter_context=bj_ctx
    )
    assert res_bj.status.value == "SUCCESS"
    assert "中国金电北京核心生产机房" in res_bj.remediation_sop
    assert "CRAC-BJ" in res_bj.remediation_sop
    # 验证严格审批策略注入
    assert "强制人工双人审批" in res_bj.remediation_sop

    # 场景 2: 在深圳边缘微模块智算中心运行
    sz_ctx = global_datacenter_manager.get_context("DC-SHENZHEN-EDGE-02")
    res_sz = await thermal_remediation_skill.execute(
        rack_id="SZ-GPU-RACK-01",
        datacenter_context=sz_ctx
    )
    assert res_sz.status.value == "SUCCESS"
    assert "深圳前海边缘AI微模块机房" in res_sz.remediation_sop
    assert "INROW-SZ-01" in res_sz.remediation_sop
    # 验证边缘自主优化策略放行注入
    assert "自主调优放行" in res_sz.remediation_sop
