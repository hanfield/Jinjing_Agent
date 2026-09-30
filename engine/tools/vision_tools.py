"""
金枢 3.0 (Jin-Shu OS) - 自研工具：多模态红外热成像与机房视觉巡检子工具箱
=============================================================================
支持对数据中心机房红外热像仪 (FLIR / Thermal Camera) 的 2D 温度场点阵矩阵进行解析，
识别机柜垂直分层温升 (Thermal Stratification)、冷热通道回流短路与局部热点；
同时对接机房轨道巡检机器人与全景摄像头，执行门禁、盲板状态与动力母线外观的视觉隐患排查。
"""

from engine.tools.base import registry, RiskLevel, get_dc_data


@registry.register(
    name="analyze_thermal_infrared_matrix",
    description="【多模态红外热成像分析】解析机房或机柜的 2D 红外热力场点阵数据。"
    "输入机柜标识（如 'RACK-A02'）或区域，计算最高温、最低温、温差梯度 ΔT，"
    "诊断机柜是否存在垂直温度分层（如上热下冷）、盲板泄漏或风道短路热点。",
    parameters={
        "type": "object",
        "properties": {
            "target_id": {
                "type": "string",
                "description": "目标机柜编号（如 'RACK-A02'）或冷通道区域（如 'COLD-AISLE-A'）"
            },
            "height_layers": {
                "type": "integer",
                "description": "垂直测温层数（默认 6 层，从 U1 底层到 U42 顶层）",
                "default": 6
            }
        },
        "required": ["target_id"]
    },
    risk_level=RiskLevel.SAFE
)
def analyze_thermal_infrared_matrix(target_id: str, height_layers: int = 6) -> str:
    """
    解析机柜垂直热分布矩阵，输出热力诊断报告
    """
    dc_data = get_dc_data()
    racks = dc_data.get("infrastructure", {}).get("racks", [])
    matched_rack = next((r for r in racks if r.get("id") == target_id), None)

    # 基础温度取自遥测或默认基准
    base_temp = matched_rack.get("temperature", 24.5) if matched_rack else 25.0
    load_ratio = matched_rack.get("load", 0.6) if matched_rack else 0.5

    # 仿真 6 层垂直温度分布（U1~U7, U8~U14, ..., U36~U42）
    layers_data = []
    layer_names = ["U1-U7(底层)", "U8-U14(中下)", "U15-U21(中部)", "U22-U28(中上)", "U29-U35(高层)", "U36-U42(顶层)"]

    stratification_severity = 1.8 if load_ratio > 0.8 else 0.8
    for i in range(min(height_layers, len(layer_names))):
        layer_temp = round(base_temp - 2.0 + (i * stratification_severity) + (0.5 if i == 5 else 0.0), 1)
        layers_data.append({
            "layer": layer_names[i],
            "temp_celsius": layer_temp,
            "status": "HOTSPOT" if layer_temp >= 31.0 else ("WARNING" if layer_temp >= 28.0 else "OPTIMAL")
        })

    temps = [item["temp_celsius"] for item in layers_data]
    max_t = max(temps)
    min_t = min(temps)
    delta_t = round(max_t - min_t, 1)

    # 诊断结论
    findings = []
    if delta_t >= 6.0:
        findings.append(f"⚠️ 垂直温差梯度过大 (ΔT={delta_t}°C)，存在显著【机柜热分层效应】。")
        findings.append("   - 诱因推断: 静电地板开孔风口可能被电缆遮挡，或顶部机柜存在假盲板脱落导致热风回流进冷通道。")
    elif max_t >= 31.0:
        findings.append(f"🚨 顶层出现局部过热靶点 ({max_t}°C)，逼近 ASHRAE TC9.9 允许上限。")
    else:
        findings.append(f"✅ 热场分布均匀 (ΔT={delta_t}°C)，冷风输送渗透良好。")

    report = [
        f"📸 【红外热成像点阵诊断 - {target_id}】",
        f"  - 最高测温点: {max_t}°C | 最低测温点: {min_t}°C | 垂直梯度差: {delta_t}°C",
        "  - 垂直断面温区点阵:",
    ]
    for item in layers_data:
        icon = "🔴" if item["status"] == "HOTSPOT" else ("🟡" if item["status"] == "WARNING" else "🟢")
        bar = "█" * int((item["temp_celsius"] - 18) * 2)
        report.append(f"    [{icon} {item['layer']}] {item['temp_celsius']}°C | {bar}")

    report.append("\n  - 空间流体力学诊断:")
    for f in findings:
        report.append(f"    {f}")

    return "\n".join(report)


@registry.register(
    name="inspect_visual_patrol_frame",
    description="【巡检机器人视觉侦测】调用机房巡检摄像头或机器人当前航道快照。"
    "对目标物理资产（如机柜门锁、指示灯、漏水感应带、电缆桥架）进行机器视觉状态核验。",
    parameters={
        "type": "object",
        "properties": {
            "asset_id": {
                "type": "string",
                "description": "核验物理目标标识（如 'RACK-A02'、'CRAC-A01' 或 'ZONE-A'）"
            },
            "inspection_item": {
                "type": "string",
                "description": "检查项：'door_status' (柜门开闭), 'leak_sensor' (地面漏水带), 'cable_tray' (母线与桥架), 'all' (全项)",
                "default": "all"
            }
        },
        "required": ["asset_id"]
    },
    risk_level=RiskLevel.SAFE
)
def inspect_visual_patrol_frame(asset_id: str, inspection_item: str = "all") -> str:
    """
    仿真机器视觉识别报告
    """
    results = [f"🤖 【机房机器人视觉巡查 - 目标: {asset_id}】"]

    if inspection_item in ("door_status", "all"):
        results.append("  - 🚪 物理柜门侦测: 密闭良好 (前网孔门闭合率 100%，压簧锁扣处于锁紧状态)")

    if inspection_item in ("leak_sensor", "all"):
        if "CRAC" in asset_id or "A01" in asset_id:
            results.append("  - 💧 地板下漏水绳侦测: 🟡 边缘识别到微量液体反光斑块，与排水支路高度重合！")
        else:
            results.append("  - 💧 地板下漏水绳侦测: 🟢 地板干燥无积水反光")

    if inspection_item in ("cable_tray", "all"):
        results.append("  - ⚡ 电缆走线与母线槽: 🟢 走线平整无挤压，母线测温贴片呈正常显色")

    return "\n".join(results)
