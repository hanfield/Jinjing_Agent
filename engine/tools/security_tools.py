"""
金枢 (Jin-Shu) - 自研工具：安防子工具箱
=============================================
包括门禁日志分析与安防巡检隐患排查工具。
"""

from engine.tools.base import registry, RiskLevel, get_dc_data

@registry.register(
    name="analyze_security",
    description="分析最近的门禁出入记录，识别外部人员进场风险，生成智能巡检建议。",
    parameters={
        "type": "object",
        "properties": {"hours": {"type": "integer", "description": "分析最近多少小时的记录，默认 2"}},
        "required": [],
    },
    risk_level=RiskLevel.SAFE,
)
def analyze_security(hours: int = 2) -> str:
    external = {}
    for entry in get_dc_data()["access_log"]:
        if entry["type"] == "外部人员" and entry["action"] == "进入":
            external.setdefault(entry["zone"], []).append(entry)

    lines = ["## 🔒 安防巡检分析报告"]
    for zone, entries in external.items():
        names = "、".join([e["person"] for e in entries])
        lines.append(f"⚠️ **外部人员活动预警**: {zone} 发现外部人员 {names} 进入机房巡检或操作。")
        lines.append("   - **巡检建议**: 请随同配合物理安检，检查随身携带物品，并确认操作授权单。")

    if not external:
        lines.append("✅ 近期无外部人员进场，安防状态正常。")
    return "\n".join(lines)
