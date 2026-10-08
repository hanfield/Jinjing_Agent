"""
金枢 3.0 (Jin-Shu OS) - 跨机房最小化零代码适配引擎 (Minimal Datacenter Adapter Engine)
========================================================================================
设计宗旨：
  为不同机房做“最小化适配”。新机房接入不需要编写任何 Python 代码或修改已有的 Skill。
  通过“预设架构模板 (Presets) + 智能点位自映射 (Semantic Point Matcher) + 动态机房画像 (DC Profile)”
  实现只需一份几十行的声明式 YAML 即可实现所有复合 Skill 的“即插即用”。

核心架构组件：
  1. SemanticPointMatcher:
     免驱动代码！自动识别华为、维谛、施耐德、动环厂商的异构遥测点位（如“回风温度”、“T_Return”、“CRAC_IN_TEMP” -> return_temp）。
  2. PresetCatalog:
     开箱即用的典型机房架构模板（标准封闭冷通道、行间冷水制冷、边缘智算微模块等）。
  3. DatacenterProfile & DatacenterContext:
     运行时统一上下文，提供相对拓扑遍历、目标环境常数和安全审批级别。
  4. DatacenterManager:
     支持多机房注册、按 ID 动态切换上下文（Multi-Tenancy Datacenter Support）。
"""

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional
import yaml

from engine.memory.topology_graph import DatacenterTopologyGraph


class SafetyPolicyLevel(str, Enum):
    """机房安全控制等级"""
    STRICT_HITL = "STRICT_HITL"             # Tier-4 金融核心: 100% 强制双人复核审批，禁止自主下发指令
    AUTONOMOUS_OPTIMIZE = "AUTONOMOUS_OPTIMIZE" # 边缘/容灾机房: 允许在安全阈值内自主调优，生成审计日志
    READ_ONLY_OBSERVE = "READ_ONLY_OBSERVE" # 仅观察推演模式


@dataclass
class ThermodynamicParameters:
    """机房专属物理与环境常数"""
    target_temp_celsius: float = 24.0
    max_vertical_delta_t: float = 4.0
    ashrae_high_limit: float = 27.0
    fan_hz_temp_slope: float = 0.45       # 每增加 1Hz 降温估算幅度 (°C/Hz)
    nominal_fan_freq: float = 42.0        # 标称常用空调频率 (Hz)


class SemanticPointMatcher:
    """
    智能点位语义自动映射器 (Self-Healing Semantic Point Matcher)
    消除驱动层代码开发：自动通过正则与中英文同义词词典，
    将异构设备上报的各类名称归一化到系统标准物模型槽位。
    """

    # 标准槽位同义词词典 (覆盖主流中英文 DCIM 厂商命名惯例)
    SLOT_SYNONYMS = {
        "supply_temp": [
            r"supply.*temp", r"出风.*温", r"送风.*温", r"t_out", r"t_supply",
            r"discharge.*temp", r"cold_air_temp"
        ],
        "return_temp": [
            r"return.*temp", r"回风.*温", r"进风.*温", r"t_in", r"t_return",
            r"intake.*temp", r"ambient_temp"
        ],
        "fan_speed_hz": [
            r"fan.*freq", r"风机.*频", r"fan.*hz", r"hz", r"blower.*speed",
            r"fan_speed_hz", r"转速.*hz"
        ],
        "power_load_percent": [
            r"load.*percent", r"负载.*率", r"load_ratio", r"power.*percent",
            r"capacity.*used", r"ups_load"
        ],
        "battery_percent": [
            r"battery.*percent", r"电池.*电量", r"battery.*soc", r"batt_level"
        ]
    }

    @classmethod
    def match_slot(cls, raw_key: str) -> Optional[str]:
        """将任意厂商原始字段名匹配到统一物理槽位"""
        raw_norm = raw_key.strip().lower()
        for slot, patterns in cls.SLOT_SYNONYMS.items():
            for pat in patterns:
                if re.search(pat, raw_norm):
                    return slot
        return None

    @classmethod
    def canonicalize_telemetry(cls, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """将厂商上报的异构遥测字典自动转化为统一物理槽位字典"""
        canonical = {}
        for k, v in raw_data.items():
            slot = cls.match_slot(k)
            if slot:
                canonical[slot] = v
            else:
                canonical[k] = v
        return canonical


class PresetCatalog:
    """典型机房拓扑预设模板库 (Convention over Configuration)"""

    @staticmethod
    def apply_standard_cold_aisle(graph: DatacenterTopologyGraph, racks: List[str], coolers: List[str], aisle_name: str = "AISLE-01"):
        """标准封闭冷通道架构模板"""
        graph.add_node(aisle_name, f"封闭冷通道 {aisle_name}", "L2_Spatial", {"containment": "COLD_AISLE"})
        for c in coolers:
            graph.add_node(c, f"精密空调 {c}", "L1_HVAC", {"type": "CRAC_CHILLED_WATER"})
            graph.add_edge(c, aisle_name, "cools")
        for r in racks:
            graph.add_node(r, f"服务器机柜 {r}", "L2_Spatial", {"rated_kw": 12.0})
            graph.add_edge(aisle_name, r, "cools")

    @staticmethod
    def apply_in_row_modular(graph: DatacenterTopologyGraph, racks: List[str], coolers: List[str], aisle_name: str = "POD-01"):
        """行级空调高密微模块架构模板"""
        graph.add_node(aisle_name, f"智算微模块 {aisle_name}", "L2_Spatial", {"containment": "IN_ROW_POD"})
        for c in coolers:
            graph.add_node(c, f"行间高密精密空调 {c}", "L1_HVAC", {"type": "IN_ROW_DX"})
            # 行级空调直接对就近机柜进行靶向强制制冷
            for r in racks:
                graph.add_edge(c, r, "cools_direct")


@dataclass
class DatacenterProfile:
    """机房声明式配置画像数据模型"""
    datacenter_id: str
    name: str
    preset_type: str = "standard_cold_aisle"
    safety_policy: SafetyPolicyLevel = SafetyPolicyLevel.STRICT_HITL
    thermodynamics: ThermodynamicParameters = field(default_factory=ThermodynamicParameters)
    aisle_name: str = "AISLE-A01"
    racks: List[str] = field(default_factory=lambda: ["RACK-01", "RACK-02"])
    coolers: List[str] = field(default_factory=lambda: ["CRAC-01"])
    custom_properties: Dict[str, Any] = field(default_factory=dict)


class DatacenterContext:
    """
    统一机房运行上下文 (Universal Datacenter Execution Context)
    向所有 Skill 屏蔽设备细节，提供统一的相对拓扑寻址和物理/安全参数。
    """

    def __init__(self, profile: DatacenterProfile):
        self.profile = profile
        self.topology = DatacenterTopologyGraph()
        self._hydrate_topology()

    def _hydrate_topology(self):
        """基于预设模板与声明清单动态建图 (见房建图)"""
        preset = self.profile.preset_type.lower()
        if "in_row" in preset or "modular" in preset:
            PresetCatalog.apply_in_row_modular(
                self.topology,
                racks=self.profile.racks,
                coolers=self.profile.coolers,
                aisle_name=self.profile.aisle_name
            )
        else:
            PresetCatalog.apply_standard_cold_aisle(
                self.topology,
                racks=self.profile.racks,
                coolers=self.profile.coolers,
                aisle_name=self.profile.aisle_name
            )

    def find_associated_coolers(self, target_rack_id: str) -> List[str]:
        """
        相对拓扑寻址：自动寻址对目标机柜负有供冷责任的空调设备标识列表。
        彻底消除 'CRAC-A01' 硬编码！
        """
        # 1. 查找上游直接相连的制冷源
        upstream = self.topology.trace_upstream_cause(target_rack_id, depth=2)
        cooler_ids = [item["node_id"] for item in upstream if item["layer"] == "L1_HVAC"]
        if cooler_ids:
            return cooler_ids
        # 2. 若未明确匹配，回退到当前机房配置的默认主空调
        return self.profile.coolers

    def requires_human_approval(self, action_risk_tier: str) -> bool:
        """根据当前机房的安全等级决策是否必须触发审批门拦截"""
        if self.profile.safety_policy == SafetyPolicyLevel.STRICT_HITL:
            # 金融核心机房，任何非只读动作或 MEDIUM/HIGH 风险强制审批
            return True
        elif self.profile.safety_policy == SafetyPolicyLevel.AUTONOMOUS_OPTIMIZE:
            # 边缘机房只有 HIGH 风险才拦截，常规调优放行
            return action_risk_tier == "HIGH"
        return True


class DatacenterManager:
    """机房统一注册与上下文管理中心 (Multi-Tenancy Manager)"""

    def __init__(self):
        self._contexts: Dict[str, DatacenterContext] = {}
        self._active_dc_id: Optional[str] = None
        self._init_default_contexts()

    def _init_default_contexts(self):
        """加载系统内置的标准参考机房"""
        default_profile = DatacenterProfile(
            datacenter_id="DEFAULT_DC",
            name="北京主数据中心示范区 (默认)",
            preset_type="standard_cold_aisle",
            safety_policy=SafetyPolicyLevel.STRICT_HITL,
            racks=["RACK-A01", "RACK-A02", "RACK-A03"],
            coolers=["CRAC-A01", "CRAC-A02"]
        )
        self.register_profile(default_profile)
        self._active_dc_id = "DEFAULT_DC"

    def register_profile(self, profile: DatacenterProfile) -> DatacenterContext:
        ctx = DatacenterContext(profile)
        self._contexts[profile.datacenter_id] = ctx
        return ctx

    def load_from_yaml(self, yaml_content_or_path: str) -> DatacenterContext:
        """从外部一份极简 YAML 声明式配置中动态水合机房"""
        if os.path.exists(yaml_content_or_path):
            with open(yaml_content_or_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        else:
            data = yaml.safe_load(yaml_content_or_path)

        meta = data.get("metadata", {})
        thermo_data = data.get("thermodynamics", {})
        thermo = ThermodynamicParameters(
            target_temp_celsius=thermo_data.get("target_temp_celsius", 24.0),
            max_vertical_delta_t=thermo_data.get("max_vertical_delta_t", 4.0),
            ashrae_high_limit=thermo_data.get("ashrae_high_limit", 27.0),
            fan_hz_temp_slope=thermo_data.get("fan_hz_temp_slope", 0.45),
            nominal_fan_freq=thermo_data.get("nominal_fan_freq", 42.0),
        )

        assets = data.get("assets", {})
        profile = DatacenterProfile(
            datacenter_id=meta.get("datacenter_id", "CUSTOM_DC"),
            name=meta.get("name", "未命名机房"),
            preset_type=data.get("preset_type", "standard_cold_aisle"),
            safety_policy=SafetyPolicyLevel(data.get("safety_policy", "STRICT_HITL")),
            thermodynamics=thermo,
            aisle_name=assets.get("aisle_name", "AISLE-01"),
            racks=assets.get("racks", ["RACK-01"]),
            coolers=assets.get("coolers", ["CRAC-01"]),
            custom_properties=data.get("custom_properties", {})
        )
        return self.register_profile(profile)

    def get_context(self, datacenter_id: Optional[str] = None) -> DatacenterContext:
        dc_id = datacenter_id or self._active_dc_id
        if dc_id and dc_id in self._contexts:
            return self._contexts[dc_id]
        return self._contexts["DEFAULT_DC"]

    def set_active_dc(self, datacenter_id: str):
        if datacenter_id in self._contexts:
            self._active_dc_id = datacenter_id


# 全局单例
global_datacenter_manager = DatacenterManager()
