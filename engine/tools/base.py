"""
金枢 (Jin-Shu) - 自研工具注册、调度与共享资源底座
======================================================
1. 替代 LangChain 的 Tool 装饰器，实现完全自主可控的工具管理。
2. 集中实例化和缓存硬件及云端的网络协议客户端。
3. 集中加载本地的静态知识库和模拟 CMDB 体征数据。
"""

import json
import logging
import math
import os
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Any, Optional, Dict, List
from urllib.parse import urlparse

import httpx

from engine.protocols import (
    SNMPClient,
    ModbusTCPClient,
    RedfishClient,
    OpenStackClient,
    K8sPrometheusClient,
    global_daemon
)

logger = logging.getLogger(__name__)

# ── 1. 工具风险与规格定义 ─────────────────────────────────────────

class RiskLevel(Enum):
    """工具风险等级"""
    SAFE = "safe"          # 只读查询，无副作用
    CAUTION = "caution"    # 可能改变配置，需确认
    DANGER = "danger"      # 高危操作（重启/断电），必须人工审批


@dataclass
class ToolSpec:
    """工具规格描述"""
    name: str                          # 工具名称（英文标识符）
    description: str                   # 功能描述（供 LLM 理解）
    parameters: dict                   # JSON Schema 格式的参数定义
    risk_level: RiskLevel = RiskLevel.SAFE
    fn: Callable = None                # 实际执行函数
    requires_approval: bool = False    # 是否需要人工审批


class ToolRegistry:
    """
    金枢工具注册中心。
    所有 Agent 可调用的工具在此统一注册、管理和调度。
    """
    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        risk_level: RiskLevel = RiskLevel.SAFE,
    ):
        """装饰器：注册一个工具函数到注册中心"""
        def decorator(fn: Callable):
            spec = ToolSpec(
                name=name,
                description=description,
                parameters=parameters,
                risk_level=risk_level,
                fn=fn,
                requires_approval=(risk_level == RiskLevel.DANGER),
            )
            self._tools[name] = spec
            return fn
        return decorator

    def get_tool(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        """
        执行指定工具。
        如果工具为 DANGER 级别，会抛出 ApprovalRequired 异常。
        """
        tool = self._tools.get(name)
        if not tool:
            return f"❌ 错误：工具 '{name}' 未注册。"

        if tool.requires_approval:
            raise ApprovalRequired(
                tool_name=name,
                arguments=arguments,
                message=f"🚨 高危操作拦截：工具 '{name}' 被标记为 DANGER 级别，"
                        f"需要值班主管审批后方可执行。"
            )

        try:
            result = tool.fn(**arguments)
            return str(result)
        except Exception as e:
            return f"❌ 工具 '{name}' 执行异常：{str(e)}"

    def get_openai_tools_schema(self) -> List[dict]:
        """
        将所有注册工具转换为 OpenAI function-calling 的 JSON Schema 格式。
        """
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            })
        return schemas


class ApprovalRequired(Exception):
    """当 DANGER 级别工具被调用时抛出，触发人工审批流程"""
    def __init__(self, tool_name: str, arguments: dict, message: str):
        self.tool_name = tool_name
        self.arguments = arguments
        super().__init__(message)


# ── 2. 共享客户端与数据资产实例化 ─────────────────────────────

# 自动拉起协议仿真后台服务
global_daemon.start()

snmp_client = SNMPClient()
modbus_client = ModbusTCPClient()
redfish_client = RedfishClient()
openstack_client = OpenStackClient()
k8s_client = K8sPrometheusClient()

registry = ToolRegistry()

# ── 加载模拟数据库与私域知识 ────────────────────────────────────
_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "datacenter_mock.json"
_KB_PATH = Path(__file__).parent.parent.parent / "data" / "expert_knowledge.md"
_PRIVATE_LIB_PATH = Path(__file__).parent.parent.parent / "data" / "private_library.json"
_FINGERPRINT_PATH = Path(__file__).parent.parent.parent / "data" / "fault_fingerprint_library.json"

with open(_KB_PATH, "r", encoding="utf-8") as f:
    _KB_TEXT = f.read()

with open(_PRIVATE_LIB_PATH, "r", encoding="utf-8") as f:
    PRIVATE_LIB = json.load(f)

try:
    with open(_FINGERPRINT_PATH, "r", encoding="utf-8") as f:
        FAULT_FINGERPRINTS = json.load(f)
except Exception:
    FAULT_FINGERPRINTS = []


# ── 3. OpenStack 真实数据调取辅助函数 ───────────────────────────
_os_token = None
_os_catalog = []
_os_project_id = None
_os_token_expiry = 0


def get_openstack_auth():
    global _os_token, _os_catalog, _os_project_id, _os_token_expiry
    if _os_token and time.time() < _os_token_expiry:
        return _os_token, _os_catalog, _os_project_id

    auth_url = os.getenv("OPENSTACK_AUTH_URL", "http://10.210.24.15:5000/v3")
    username = os.getenv("OPENSTACK_USERNAME", "admin")
    password = os.getenv("OPENSTACK_PASSWORD", "000000")
    project_name = os.getenv("OPENSTACK_PROJECT_NAME", "admin")

    payload = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": username,
                        "domain": {"name": "DEFAULT"},
                        "password": password,
                    }
                },
            },
            "scope": {
                "project": {
                    "name": project_name,
                    "domain": {"name": "DEFAULT"},
                }
            },
        }
    }

    headers = {"Content-Type": "application/json"}
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(f"{auth_url}/auth/tokens", json=payload, headers=headers)
        if resp.status_code != 201:
            raise Exception(f"Keystone Auth Failed: {resp.status_code} - {resp.text}")

        _os_token = resp.headers.get("X-Subject-Token")
        body = resp.json()
        _os_catalog = body.get("token", {}).get("catalog", [])
        _os_project_id = body.get("token", {}).get("project", {}).get("id")
        _os_token_expiry = time.time() + 28 * 60  # 缓存 28 分钟
        return _os_token, _os_catalog, _os_project_id


def resolve_os_endpoint(catalog, service_type):
    auth_url = os.getenv("OPENSTACK_AUTH_URL", "http://10.210.24.15:5000/v3")
    try:
        auth_ip = urlparse(auth_url).hostname
    except Exception:
        auth_ip = "10.210.24.15"

    svc = next((c for c in catalog if c["type"] == service_type), None)
    if not svc:
        return None

    ep = next(
        (e for e in svc.get("endpoints", []) if e["interface"] in ("public", "internal")),
        None,
    )
    if not ep:
        return None

    url = ep["url"]
    try:
        parsed = urlparse(url)
        if parsed.hostname != auth_ip:
            port = f":{parsed.port}" if parsed.port else ""
            url = f"{parsed.scheme}://{auth_ip}{port}{parsed.path}"
    except Exception:
        pass
    return url


def fetch_real_openstack_resources() -> dict:
    """从真实的 OpenStack API 中拉取服务器、网络、硬盘等资源"""
    return openstack_client.fetch_all_resources()


def fetch_real_k8s_resources() -> dict:
    """从 K8s API Server 中拉取节点(Nodes)与容器组(Pods)的运行态"""
    return k8s_client.fetch_k8s_resources()


# ── 4. 高保真机房体征数据提取 ───────────────────────────────────

def get_dc_data() -> dict:
    # 动态通过协议客户端网络调用查询状态，保持高保真数据调用
    try:
        raw = global_daemon.state
    except Exception:
        raw = {}

    flat = {
        "racks": [],
        "ups": [],
        "hvac": [],
        "servers": [],
        "access_log": [],
        "history_metrics": raw.get("history_metrics", {}),
        "network_traffic": raw.get("network_traffic", []),
    }

    # 1. 物理设施层 - SNMP 协议读取 UPS 负载
    for dc in raw.get("datacenters", []):
        for ups in dc.get("ups", []):
            ups_id = ups["id"]
            unit = 1 if "01" in ups_id else 2
            load = snmp_client.get_oid(f"1.3.6.1.4.1.9.9.ups.{unit}.load")
            battery = snmp_client.get_oid(f"1.3.6.1.4.1.9.9.ups.{unit}.battery")

            flat["ups"].append({
                "id": ups_id,
                "zone": ups["zone"],
                "load_percent": int(load) if load else ups["load_percent"],
                "battery_percent": int(battery) if battery else ups["battery_percent"],
                "output_kva": ups["output_kva"]
            })

    # 2. 物理设施层 - Modbus/TCP 协议读取精密空调 HVAC
    for dc in raw.get("datacenters", []):
        for hvac in dc.get("hvac", []):
            hvac_id = hvac["id"]
            unit_id = 1 if "01" in hvac_id else 2
            regs = modbus_client.read_holding_registers(unit_id=unit_id, start_address=0, quantity=4)
            if regs and len(regs) >= 4:
                supply = float(regs[0]) / 10.0
                ret = float(regs[1]) / 10.0
                speed = regs[2]
                status = "正常" if regs[3] == 1 else "故障"
            else:
                supply = hvac["supply_temp"]
                ret = hvac["return_temp"]
                speed = hvac["fan_speed_hz"]
                status = hvac["status"]

            flat["hvac"].append({
                "id": hvac_id,
                "zone": hvac["zone"],
                "supply_temp": supply,
                "return_temp": ret,
                "fan_speed_hz": speed,
                "status": status
            })

    # 3. 物理主机层 - Redfish 协议读取服务器与机柜热体征
    for dc in raw.get("datacenters", []):
        # 3.1 机柜温度
        for rack in dc.get("racks", []):
            rack_id = rack["id"]
            thermal = redfish_client.get_chassis_thermal(chassis_id=rack_id)
            temp = rack["temp_celsius"]
            if thermal and "Temperatures" in thermal:
                temp = thermal["Temperatures"][0]["ReadingCelsius"]

            flat["racks"].append({
                "id": rack_id,
                "zone": rack["zone"],
                "floor": rack["floor"],
                "power_kw": rack["power_kw"],
                "max_capacity_kw": rack["max_capacity_kw"],
                "temp_celsius": temp,
                "status": "告警" if temp > 30 else "正常"
            })

        # 3.2 物理服务器
        for s in dc.get("servers", []):
            svr_id = s["id"]
            telemetry = redfish_client.get_system_telemetry(system_id=svr_id)
            if telemetry and "Oem" in telemetry:
                cpu = telemetry["Oem"]["Telemetry"]["CPUUtilizationPercent"]
                mem = telemetry["Oem"]["Telemetry"]["MemoryUtilizationPercent"]
            else:
                cpu = s["cpu_percent"]
                mem = s["mem_percent"]

            status = "正常"
            if cpu > 90:
                status = "CPU高负载告警"
            elif mem > 90:
                status = "内存超载告警"

            flat["servers"].append({
                "id": svr_id,
                "hostname": s["hostname"],
                "ip": s.get("ip", "10.0.0.1"),
                "cpu_percent": cpu,
                "mem_percent": mem,
                "disk_percent": s["disk_percent"],
                "status": status,
                "zone": s.get("zone", "nova")
            })

        # 3.3 门禁记录
        flat["access_log"].extend(dc.get("access_log", []))

    return flat


# ── 5. 语义与时序计算内核 ──────────────────────────────────────

def _calculate_tf_idf_score(query: str, doc_text: str, all_docs: list) -> float:
    """轻量级 TF-IDF 模拟算法，用于无外部向量库语义召回"""
    import re
    # 分词（模拟）
    def tokenize(text):
        return re.findall(r"[\u4e00-\u9fa5]{1,}|[a-zA-Z0-9\-]{2,}", text.lower())

    query_tokens = tokenize(query)
    doc_tokens = tokenize(doc_text)

    if not query_tokens:
        return 0.0

    score = 0.0
    for token in query_tokens:
        tf = doc_tokens.count(token) / max(1, len(doc_tokens))
        docs_with_token = sum(1 for d in all_docs if token in (d["content"] + d["source"]).lower())
        idf = math.log(len(all_docs) / (1 + docs_with_token)) + 1.0
        score += tf * idf

    return score


def _cosine_similarity(vec1: dict, vec2: dict) -> float:
    """计算两个多维数值向量之间的夹角余弦相似度"""
    keys = set(vec1.keys()) & set(vec2.keys())
    if not keys:
        return 0.0
    dot_product = sum(vec1[k] * vec2[k] for k in keys)
    mag1 = math.sqrt(sum(v**2 for v in vec1.values()))
    mag2 = math.sqrt(sum(v**2 for v in vec2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot_product / (mag1 * mag2)


def _analyze_time_series_anomaly(history: list, current_val: float, k: float = 2.0):
    """动态自适应基带包络线计算，识别发散特征"""
    if len(history) < 3:
        return False, 0.0, 0.0, 0.0, 0.0

    vals = [h.get("load") or h.get("cpu") or 0.0 for h in history]
    mean = sum(vals) / len(vals)
    variance = sum((v - mean) ** 2 for v in vals) / len(vals)
    std_dev = math.sqrt(variance)

    upper_bound = mean + k * std_dev
    is_anomaly = current_val > upper_bound
    slope = (vals[-1] - vals[-2]) if len(vals) >= 2 else 0.0
    acceleration = (vals[-1] - 2 * vals[-2] + vals[-3]) if len(vals) >= 3 else 0.0

    return is_anomaly, upper_bound, mean, slope, acceleration
