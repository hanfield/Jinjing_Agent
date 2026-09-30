import os
from abc import ABC, abstractmethod
from typing import List, Optional
from dataclasses import dataclass, asdict

from engine.protocols import (
    SNMPClient,
    ModbusTCPClient,
    RedfishClient,
    global_daemon
)

snmp_client = SNMPClient()
modbus_client = ModbusTCPClient()
redfish_client = RedfishClient()

def _load_data() -> dict:
    # 从 daemon.state 中拉取静态结构，并通过协议客户端拉取实时监控体征
    try:
        raw = global_daemon.state
    except Exception:
        raw = {}

    import copy
    state_copy = copy.deepcopy(raw)

    for dc in state_copy.get("datacenters", []):
        # 1. SNMP 协议读取 UPS 负载
        for ups in dc.get("ups", []):
            ups_id = ups["id"]
            unit = 1 if "01" in ups_id else 2
            load = snmp_client.get_oid(f"1.3.6.1.4.1.9.9.ups.{unit}.load")
            battery = snmp_client.get_oid(f"1.3.6.1.4.1.9.9.ups.{unit}.battery")
            if load:
                ups["load_percent"] = int(load)
            if battery:
                ups["battery_percent"] = int(battery)

        # 2. Modbus/TCP 协议读取精密空调
        for hvac in dc.get("hvac", []):
            hvac_id = hvac["id"]
            unit_id = 1 if "01" in hvac_id else 2
            regs = modbus_client.read_holding_registers(unit_id=unit_id, start_address=0, quantity=4)
            if regs and len(regs) >= 4:
                hvac["supply_temp"] = float(regs[0]) / 10.0
                hvac["return_temp"] = float(regs[1]) / 10.0
                hvac["fan_speed_hz"] = regs[2]
                hvac["status"] = "正常" if regs[3] == 1 else "故障"

        # 3. Redfish 协议读取服务器与机柜体征
        for rack in dc.get("racks", []):
            rack_id = rack["id"]
            thermal = redfish_client.get_chassis_thermal(chassis_id=rack_id)
            if thermal and "Temperatures" in thermal:
                rack["temp_celsius"] = thermal["Temperatures"][0]["ReadingCelsius"]
                rack["status"] = "告警" if rack["temp_celsius"] > 30 else "正常"

        for s in dc.get("servers", []):
            svr_id = s["id"]
            telemetry = redfish_client.get_system_telemetry(system_id=svr_id)
            if telemetry and "Oem" in telemetry:
                cpu = telemetry["Oem"]["Telemetry"]["CPUUtilizationPercent"]
                mem = telemetry["Oem"]["Telemetry"]["MemoryUtilizationPercent"]
                s["cpu_percent"] = cpu
                s["mem_percent"] = mem

                status = "正常"
                if cpu > 90:
                    status = "CPU高负载告警"
                elif mem > 90:
                    status = "内存超载告警"
                s["status"] = status

    return state_copy

# ── 统一标准化告警模型 ─────────────────────────────────────
@dataclass
class AlertObject:
    id: str
    level: str          # danger, warning, info
    title: str
    detail: str
    suggestion: str
    layer: str = "Infrastructure"
    dc_id: str = ""
    dc_name: str = ""
    raw_data: Optional[dict] = None

    def to_dict(self):
        return asdict(self)

class BaseMonitor(ABC):
    @abstractmethod
    def fetch_alerts(self, dc_id: str = None) -> List[AlertObject]:
        pass

class MockMonitor(BaseMonitor):
    def fetch_alerts(self, dc_id: str = None) -> List[AlertObject]:
        try:
            data = _load_data()
        except Exception:
            return []

        alerts = []
        datacenters = data.get("datacenters", [])

        # 支持按 dc_id 过滤，不传则汇总所有机房
        if dc_id:
            datacenters = [dc for dc in datacenters if dc["id"] == dc_id]

        for dc in datacenters:
            dc_id_val = dc["id"]
            dc_name = dc["name"]

            # 1. 机柜温度告警
            for rack in dc.get("racks", []):
                if rack["temp_celsius"] > 30:
                    alerts.append(AlertObject(
                        id=f"{dc_id_val}:{rack['id']}", level="danger",
                        title=f"{rack['id']} 机柜高温告警",
                        detail=f"{dc_name} | {rack['zone']} | 温度 {rack['temp_celsius']}°C（阈值 30°C）| 功耗 {rack['power_kw']}kW",
                        suggestion=f"查询：{dc_name}的 {rack['id']} 高温应该怎么处理？",
                        layer="Infrastructure", dc_id=dc_id_val, dc_name=dc_name, raw_data=rack
                    ))
                elif rack["temp_celsius"] > 27:
                    alerts.append(AlertObject(
                        id=f"{dc_id_val}:{rack['id']}", level="warning",
                        title=f"{rack['id']} 温度偏高",
                        detail=f"{dc_name} | {rack['zone']} | 温度 {rack['temp_celsius']}°C",
                        suggestion=f"查询：{dc_name}的 {rack['id']} 温度偏高需要注意什么？",
                        layer="Infrastructure", dc_id=dc_id_val, dc_name=dc_name, raw_data=rack
                    ))

            # 2. UPS 负载告警
            for ups in dc.get("ups", []):
                if ups["load_percent"] > 80:
                    alerts.append(AlertObject(
                        id=f"{dc_id_val}:{ups['id']}", level="danger",
                        title=f"{ups['id']} UPS 负载过高",
                        detail=f"{dc_name} | {ups['zone']} | 负载率 {ups['load_percent']}% | 电池 {ups['battery_percent']}%",
                        suggestion=f"查询：{dc_name}的 {ups['id']} UPS 负载过高怎么处理？",
                        layer="Infrastructure", dc_id=dc_id_val, dc_name=dc_name, raw_data=ups
                    ))

            # 3. HVAC 故障告警
            for hvac in dc.get("hvac", []):
                if hvac["status"] == "故障":
                    alerts.append(AlertObject(
                        id=f"{dc_id_val}:{hvac['id']}", level="danger",
                        title=f"{hvac['id']} 精密空调故障",
                        detail=f"{dc_name} | {hvac['zone']} | 回风温度 {hvac['return_temp']}°C | 状态: {hvac['status']}",
                        suggestion=f"查询：{dc_name} 空调 {hvac['id']} 出现故障该怎么办？",
                        layer="Infrastructure", dc_id=dc_id_val, dc_name=dc_name, raw_data=hvac
                    ))

            # 4. 服务器负载告警
            for s in dc.get("servers", []):
                if "告警" in s["status"]:
                    alerts.append(AlertObject(
                        id=f"{dc_id_val}:{s['id']}", level="warning",
                        title=f"{s['id']} 服务器告警",
                        detail=f"{dc_name} | {s['hostname']} | CPU {s['cpu_percent']}% | 内存 {s['mem_percent']}% | {s['status']}",
                        suggestion=f"查询：{dc_name} 的 {s['hostname']} 出现 {s['status']}，该如何处理？",
                        layer="Application", dc_id=dc_id_val, dc_name=dc_name, raw_data=s
                    ))

            # 5. 安防告警
            external = [e for e in dc.get("access_log", []) if e["type"] == "外部人员" and e["action"] == "进入"]
            if len(external) >= 2:
                names = "、".join([e["person"] for e in external])
                alerts.append(AlertObject(
                    id=f"{dc_id_val}:sec-001", level="warning",
                    title=f"安防：{external[0]['zone']} 外部人员进场告警",
                    detail=f"{dc_name} | {len(external)} 名外部人员在场：{names}",
                    suggestion=f"查询：{dc_name} 有外部维保人员在场，安防该怎么处理？",
                    layer="Security", dc_id=dc_id_val, dc_name=dc_name, raw_data={"names": names}
                ))

        return alerts

class ExternalAPIMonitor(BaseMonitor):
    def __init__(self, api_url: str, token: str):
        self.api_url = api_url
        self.token = token

    def fetch_alerts(self, dc_id: str = None) -> List[AlertObject]:
        # [TODO: 接入公司真实 O&M API，按 dc_id 过滤]
        return []

class MonitoringService:
    """统一告警总线编排器"""
    def __init__(self):
        self.mode = os.getenv("MONITOR_MODE", "MOCK")
        if self.mode == "EXTERNAL_API":
            api_url = os.getenv("MONITOR_API_URL", "http://internal-cmdb/v1/alerts")
            token = os.getenv("MONITOR_API_TOKEN", "")
            self.monitor = ExternalAPIMonitor(api_url, token)
        else:
            self.monitor = MockMonitor()

    def get_alerts(self, dc_id: str = None) -> List[dict]:
        return [a.to_dict() for a in self.monitor.fetch_alerts(dc_id=dc_id)]

    def get_datacenters(self) -> List[dict]:
        """返回所有机房的汇总信息（用于前端下拉选择）"""
        try:
            data = _load_data()
            summary = []
            for dc in data.get("datacenters", []):
                rack_count = len(dc.get("racks", []))
                alert_count = sum(1 for r in dc.get("racks", []) if r["status"] == "告警")
                summary.append({
                    "id": dc["id"],
                    "name": dc["name"],
                    "city": dc["city"],
                    "type": dc.get("type", ""),
                    "rack_count": rack_count,
                    "alert_count": alert_count,
                    "status": "告警" if alert_count > 0 else "正常"
                })
            return summary
        except Exception:
            return []

# 全局实例
monitoring_service = MonitoringService()
