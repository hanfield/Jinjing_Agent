"""
金枢 (Jin-Shu) - 自研工具：物理基础设施及动环子工具箱
=========================================================
包括数据中心体征查询、空调制冷能效分析、多变量动态基线检测、业务突发流量负荷预测、个体数字指纹靶向预警及前端物理拓扑渲染等工具。
"""

from engine.tools.base import (
    registry,
    RiskLevel,
    get_dc_data,
    fetch_real_openstack_resources,
    fetch_real_k8s_resources,
    FAULT_FINGERPRINTS,
    _analyze_time_series_anomaly,
    _cosine_similarity
)

# ═══════════════════════════════════════════════════════════
# 工具 1：数据中心设施查询（安全级）
# ═══════════════════════════════════════════════════════════

@registry.register(
    name="query_infrastructure",
    description="查询数据中心的基础设施状态，包括机柜、UPS、HVAC 空调及服务器。"
    "输入关键词，如区域名（A区）、设备类型（ups、hvac、服务器）等。",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "查询关键词，如 'A区'、'ups'、'服务器' 等"}},
        "required": ["query"],
    },
    risk_level=RiskLevel.SAFE,
)
def query_infrastructure(query: str = "") -> str:
    if not query:
        return "⚠️ 请提供特定的 `query` 参数进行查询，如 'A区'、'ups'。"
    query_lower = query.lower()
    result_parts = []

    # ── 1. 尝试从真实 OpenStack 加载云资源 ───────────────────────────
    real_data = fetch_real_openstack_resources()

    # 服务器/虚拟机
    if (
        "server" in query_lower
        or "服务器" in query_lower
        or "vm" in query_lower
        or "虚拟机" in query_lower
        or "实例" in query_lower
    ):
        if real_data and real_data.get("servers"):
            result_parts.append("\n=== 🖥️ OpenStack 真实云服务器实例 (Real-Time) ===")
            for s in real_data["servers"]:
                icon = "🟢" if s["status"] == "ACTIVE" else "🟡" if s["status"] == "BUILD" else "🔴"
                ips_str = ", ".join(s["ips"]) if s["ips"] else "无 IP"
                result_parts.append(
                    f"{icon} 实例名: {s['name']} | ID: {s['id']}\n"
                    f"   IP: {ips_str} | 规格: {s['spec']} | 可用区: {s['zone']} | 状态: {s['status']}"
                )
        else:
            result_parts.append("\n=== 🖥️ 基础设施物理服务器 (Fallback / Mock) ===")
            for s in get_dc_data()["servers"]:
                icon = "🔴" if "告警" in s["status"] else "🟢"
                result_parts.append(
                    f"{icon} {s['id']} ({s['hostname']}) | "
                    f"CPU: {s['cpu_percent']}% | 内存: {s['mem_percent']}% | 状态: {s['status']}"
                )

    # 网络 (Neutron)
    if "network" in query_lower or "网络" in query_lower or "neutron" in query_lower:
        if real_data and real_data.get("networks"):
            result_parts.append("\n=== 🌐 OpenStack 真实虚拟网络 (Real-Time) ===")
            for n in real_data["networks"]:
                icon = "🟢" if n["status"] == "ACTIVE" else "🔴"
                result_parts.append(f"{icon} 网络名: {n['name']} | ID: {n['id']} | 状态: {n['status']}")
        else:
            result_parts.append("\n⚠️ [OpenStack 网络] 未查询到真实网络资源或接口不可用。")

    # 云硬盘 (Cinder)
    if "volume" in query_lower or "云硬盘" in query_lower or "存储" in query_lower or "cinder" in query_lower:
        if real_data and real_data.get("volumes"):
            result_parts.append("\n=== 💾 OpenStack 真实云硬盘卷 (Real-Time) ===")
            for v in real_data["volumes"]:
                icon = "🟢" if v["status"] == "available" or v["status"] == "in-use" else "🟡"
                result_parts.append(
                    f"{icon} 硬盘名: {v['name']} | 容量: {v['size']} GB | 类型: {v['type']} | 状态: {v['status']} | ID: {v['id']}"
                )
        else:
            result_parts.append("\n⚠️ [OpenStack 存储] 未查询到真实云硬盘资源或接口不可用。")

    # 镜像 (Glance)
    if "image" in query_lower or "镜像" in query_lower or "glance" in query_lower:
        if real_data and real_data.get("images"):
            result_parts.append("\n=== 💿 OpenStack 真实系统镜像 (Real-Time) ===")
            for img in real_data["images"]:
                icon = "🟢" if img["status"] == "active" else "🟡"
                result_parts.append(f"{icon} 镜像名: {img['name']} | 状态: {img['status']} | ID: {img['id']}")
        else:
            result_parts.append("\n⚠️ [OpenStack 镜像] 未查询到真实镜像资源或接口不可用。")

    # ── 2. 动环物理设施 (机柜、UPS、空调) ───────────────
    # 机柜
    if (
        query_lower in "racks"
        or "机柜" in query_lower
        or "rack" in query_lower
        or query_lower in "a区"
        or query_lower in "b区"
    ):
        result_parts.append("\n=== 📦 机房物理机柜监控 ===")
        for r in get_dc_data()["racks"]:
            if (
                query_lower in r["zone"].lower()
                or query_lower in r["id"].lower()
                or "机柜" in query
                or "rack" in query_lower
            ):
                icon = "🔴" if r["status"] == "告警" else "🟢"
                result_parts.append(
                    f"{icon} {r['id']} | {r['zone']} {r['floor']}楼 | "
                    f"功耗 {r['power_kw']}/{r['max_capacity_kw']} kW | "
                    f"温度 {r['temp_celsius']}°C | 状态: {r['status']}"
                )

    # UPS
    if "ups" in query_lower or "电源" in query_lower or "不间断" in query_lower:
        result_parts.append("\n=== ⚡ 机房 UPS 电源监控 ===")
        for u in get_dc_data()["ups"]:
            icon = "🔴" if u["load_percent"] > 80 else "🟢"
            result_parts.append(
                f"{icon} {u['id']} | 区域: {u['zone']} | "
                f"负载率: {u['load_percent']}% | 电池: {u['battery_percent']}% | 输出: {u['output_kva']} kVA"
            )

    # 空调
    if "hvac" in query_lower or "空调" in query_lower or "制冷" in query_lower:
        result_parts.append("\n=== ❄️ 机房 HVAC 精密空调监控 ===")
        for h in get_dc_data()["hvac"]:
            result_parts.append(
                f"❄️ {h['id']} | 区域: {h['zone']} | "
                f"送风: {h['supply_temp']}°C | 回风: {h['return_temp']}°C | 风机: {h['fan_speed_hz']}Hz"
            )

    # ── 3. Kubernetes 云原生集群拓扑查询 ───────────────
    if (
        "k8s" in query_lower
        or "kubernetes" in query_lower
        or "pod" in query_lower
        or "node" in query_lower
        or "容器" in query_lower
    ):
        k8s_data = fetch_real_k8s_resources()
        if k8s_data and (k8s_data.get("nodes") or k8s_data.get("pods")):
            result_parts.append("\n=== ☸️ Kubernetes 容器集群拓扑 (Real-Time) ===")

            # Nodes
            result_parts.append("【K8s 集群节点 (Nodes)】")
            for n in k8s_data.get("nodes", []):
                icon = "🟢" if n["status"] == "Ready" else "🔴"
                result_parts.append(f"{icon} 节点: {n['name']} | 状态: {n['status']}")

            # Pods
            result_parts.append("【K8s 业务容器 (Pods - Prod Namespace)】")
            for p in k8s_data.get("pods", []):
                icon = "🟢" if p["phase"] == "Running" else "🟡" if p["phase"] == "Pending" else "🔴"
                result_parts.append(f"{icon} Pod: {p['name']} | 命名空间: {p['namespace']} | Phase: {p['phase']}")

    return "\n".join(result_parts) if result_parts else "未找到匹配的设施或云资源信息。"


# ═══════════════════════════════════════════════════════════
# 工具 2：制冷效率分析（安全级）
# ═══════════════════════════════════════════════════════════

@registry.register(
    name="analyze_cooling",
    description="分析指定区域（或全部）的能效与制冷状况，关联功耗与空调参数，给出优化建议。"
    "输入区域名如 'A区'、'B区'，或 'all'。",
    parameters={
        "type": "object",
        "properties": {"zone": {"type": "string", "description": "区域名称，如 'A区' 或 'all'"}},
        "required": ["zone"],
    },
    risk_level=RiskLevel.SAFE,
)
def analyze_cooling(zone: str = "all") -> str:
    risks, recs = [], []

    for rack in get_dc_data()["racks"]:
        if zone != "all" and zone not in rack["zone"]:
            continue
        load_rate = rack["power_kw"] / rack["max_capacity_kw"]
        temp = rack["temp_celsius"]

        if temp > 28 and load_rate > 0.8:
            risks.append(f"🔴 高风险 | {rack['id']} ({rack['zone']}) | 温度 {temp}°C / 负载率 {load_rate:.0%}")
        elif temp > 26 or load_rate > 0.75:
            risks.append(f"🟡 预警 | {rack['id']} ({rack['zone']}) | 温度 {temp}°C / 负载率 {load_rate:.0%}")

    for hvac in get_dc_data()["hvac"]:
        if zone != "all" and zone not in hvac["zone"]:
            continue
        dt = hvac["return_temp"] - hvac["supply_temp"]
        if dt > 12:
            recs.append(f"💡 {hvac['id']} 温差 {dt:.1f}°C，效率良好，可适当降低风机频率节能。")
        elif dt < 8:
            recs.append(f"⚠️ {hvac['id']} 温差仅 {dt:.1f}°C，建议检查冷热通道隔离。")

    lines = ["## 🌡️ 制冷效率分析报告"]
    if risks:
        lines += ["### 风险告警"] + risks
    if recs:
        lines += ["### 优化建议"] + recs
    if not risks and not recs:
        lines.append("✅ 所有区域制冷状态正常。")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 工具 3：多变量动态基线检测（安全级）
# ═══════════════════════════════════════════════════════════

@registry.register(
    name="analyze_dynamic_baseline",
    description="引入多变量深度时序联合分析逻辑，学习算力指标拓扑关系，拟合具备包络特征的“动态自适应基线”。"
    "识别时序发散的“未知风险”实现前置处理。",
    parameters={
        "type": "object",
        "properties": {"device_id": {"type": "string", "description": "设备 ID，如 'UPS-A-01' 或 'SVR-003'"}},
        "required": ["device_id"],
    },
    risk_level=RiskLevel.SAFE,
)
def analyze_dynamic_baseline(device_id: str = "") -> str:
    if not device_id:
        return "⚠️ 调用失败：必须指定具体的 device_id 参数（例如 'UPS-A-01' 或 'SVR-003'）。请提供有效的 device_id。"

    history = get_dc_data().get("history_metrics", {}).get(device_id, [])
    if not history:
        return f"⚠️ 样本不足：未找到 {device_id} 的长轴采样数据，无法完成深度预测拟合。"

    # 获取实时当前值
    current_val = 0.0
    if "UPS" in device_id:
        u = next((x for x in get_dc_data()["ups"] if x["id"] == device_id), None)
        current_val = u["load_percent"] if u else 0.0
    elif "SVR" in device_id:
        s = next((x for x in get_dc_data()["servers"] if x["id"] == device_id), None)
        current_val = s["cpu_percent"] if s else 0.0

    # 深度时序包络计算（解包 5 个值，防止 unpack error）
    is_anomaly, upper, mean, slope, _ = _analyze_time_series_anomaly(history, current_val)

    lines = [f"## 📈 深度时序分析报告: {device_id}"]
    lines.append(f"- **实时感知值**: {current_val}%")
    lines.append(f"- **动态包络基带 (Baseline Envelope)**: {max(0, mean-5):.1f}% ~ {upper:.1f}%")
    lines.append(f"- **时序发散趋势 (Divergent Trend)**: {slope:+.2f}% / min")

    if is_anomaly or slope > 0.8:
        lines.append("\n🚨 **[未知风险预判：发散性风险熔断触发]**")
        lines.append("   - **判研特征**: 指标已背离自适应基线。虽然可能未触及静态报警，但包络线预测即将“越界发散”。")
        lines.append("   - **决策建议**: 立即执行「预见性消杀」。建议前端排查任务队列，并前置制冷预案。")
    else:
        lines.append("\n✅ **[安全判研]**: 指标波动符合时序平稳特征。运行参数处于动态基带中心，未捕获未知风险。")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 工具 4：业务流量预测负荷（安全级）
# ═══════════════════════════════════════════════════════════

@registry.register(
    name="predict_load_by_traffic",
    description="读取业务突发流量并发（TPS）并基于时序预测 IT 算力负荷与发热趋势，给出超前的「主动节能」空调预冷与防御建议。",
    parameters={
        "type": "object",
        "properties": {"zone": {"type": "string", "description": "区域名称，如 'A区'"}},
        "required": ["zone"],
    },
    risk_level=RiskLevel.SAFE,
)
def predict_load_by_traffic(zone: str = "all") -> str:
    lines = [f"## 📈 时序负载波动预测: {zone}"]
    traffic_data = get_dc_data().get("network_traffic", [])
    found = False

    for t in traffic_data:
        if t["zone"] == zone or zone == "all" or zone in t["zone"]:
            found = True
            related_racks = "、".join(t["related_racks"])
            if t["status"] == "正常":
                lines.append(
                    f"✅ {t['zone']} 并发流量 {t['current_tps']} TPS (趋势 {t['tps_trend_15m']})。算力负荷与环境热量预计平稳。"
                )
            else:
                lines.append(
                    f"⚠️ **捕获流量突发**: {t['zone']} 当前流量激增至 {t['current_tps']} TPS (趋势 {t['tps_trend_15m']})。"
                )
                lines.append(f"   - **关联算力组**: {related_racks}")
                lines.append(f"   - **预测算力骤增**: {t['predicted_cpu_surge']}")
                lines.append(f"   - **预测热量飙升**: 15 分钟内上升 {t['predicted_temp_surge']}°C")
                lines.append(
                    "💡 **主动节能与防范**: 基于动态热力学演算，前区热值即将大幅升高！建议抢在高温告警触发前进行**事前预测介入**，将关联区域冷通道气流风机频率提升 5-10Hz 进行预冷。"
                )

    if not found:
        return f"未找到 {zone} 的业务流量预测数据。"

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 工具 5：基于历史指纹的靶向预警（安全级）
# ═══════════════════════════════════════════════════════════

@registry.register(
    name="fingerprint_early_warning",
    description="个体设备级的高精度数字指纹预警探针。遍历当前机房各个物理和逻辑设备，提取每一台独立设备的微观体征，与历史同类设备的『崩溃/宕机前病理指纹』进行余弦计算。实现针对每一台单一靶点设备的精准定位和预警推演。",
    parameters={"type": "object", "properties": {}, "required": []},
    risk_level=RiskLevel.SAFE,
)
def fingerprint_early_warning() -> str:
    racks = get_dc_data()["racks"]
    ups = get_dc_data()["ups"]
    servers = get_dc_data()["servers"]

    lines = ["## 🔍 核心设备独立数字靶向预警推演"]
    lines.append("> 引擎已接管底层数据总线，正在向历史库并发投递物理层与应用层设备的个体高逼真数字体征...")

    has_warning = False

    # 1. 检测 Server 层个体
    server_fps = [fp for fp in FAULT_FINGERPRINTS if fp.get("device_type") == "SERVER"]
    for s in servers:
        s_vec = {
            "cpu_percent": s.get("cpu_percent", 0),
            "mem_percent": s.get("mem_percent", 0),
            "disk_percent": s.get("disk_percent", 0),
        }
        for fp in server_fps:
            sim = _cosine_similarity(s_vec, fp.get("pre_fault_fingerprint", {}))
            if sim > 0.85:
                has_warning = True
                lines.append(f"\n🚨 **[服务器高危预警] 发现靶点：{s['id']} (主机名: {s.get('hostname', '未知')})**")
                lines.append(f"   - **【图谱层】空间足迹**: 位于机柜 {s.get('rack_id', '未知')}")
                lines.append(f"   - **【相似层】指纹吻合度**: {sim*100:.1f}% (高度复刻)")
                lines.append(f"   - **【历史层】对齐病理**: [{fp['fingerprint_id']}] {fp['fault_type']}")
                lines.append(f"   - **【预测层】崩溃倒计时**: 核心内核预计于 **{fp['lead_time_minutes']} 分钟**后失控")
                lines.append(f"   - **【专家层】处方建议**: {fp['resolution_summary']}")

    # 2. 检测 Rack 层个体
    rack_fps = [fp for fp in FAULT_FINGERPRINTS if fp.get("device_type") == "RACK"]
    for r in racks:
        pkw = r.get("power_kw", 0)
        mkw = r.get("max_capacity_kw", 20.0)
        r_vec = {"temp_celsius": r.get("temp_celsius", 25.0), "load_ratio": pkw / mkw if mkw else 0}
        for fp in rack_fps:
            sim = _cosine_similarity(r_vec, fp.get("pre_fault_fingerprint", {}))
            if sim > 0.85:
                has_warning = True
                lines.append(f"\n🚨 **[机柜热力预警] 发现靶点：{r['id']} (区域: {r.get('zone', '未知')})**")
                lines.append(f"   - **【图谱层】空间足迹**: 位于机房 {r.get('zone', '未知')}")
                lines.append(f"   - **【相似层】热岛指纹吻合度**: {sim*100:.1f}%")
                lines.append(f"   - **【历史层】对齐病理**: [{fp['fingerprint_id']}] {fp['fault_type']}")
                lines.append(
                    f"   - **【预测层】物理红线倒计时**: 局部积热发散预计于 **{fp['lead_time_minutes']} 分钟**后突破上限"
                )
                lines.append(f"   - **【专家层】处方建议**: {fp['resolution_summary']}")

    # 3. 检测 UPS 层个体
    ups_fps = [fp for fp in FAULT_FINGERPRINTS if fp.get("device_type") == "UPS"]
    for u in ups:
        u_vec = {"load_percent": u.get("load_percent", 0), "battery_percent": u.get("battery_percent", 100)}
        for fp in ups_fps:
            sim = _cosine_similarity(u_vec, fp.get("pre_fault_fingerprint", {}))
            if sim > 0.85:
                has_warning = True
                lines.append(f"\n🚨 **[UPS供电预警] 发现靶点：{u['id']} (区域: {u.get('zone', '未知')})**")
                lines.append(f"   - **【图谱层】空间足迹**: 位于 {u.get('zone', '未知')} 能源支路")
                lines.append(f"   - **【相似层】指纹吻合度**: {sim*100:.1f}% (强相关)")
                lines.append(f"   - **【历史层】对齐病理**: [{fp['fingerprint_id']}] {fp['fault_type']}")
                lines.append(f"   - **【预测层】生存窗口**: 预计续航仅存 **{fp['lead_time_minutes']} 分钟**")
                lines.append(f"   - **【专家层】处方建议**: {fp['resolution_summary']}")

    if not has_warning:
        lines.append(
            "\n✅ **并发降维普查完成：当前所有微观设备的运行体征均未突破独立报警红线，未检出任何已知的个体级恶性隐患指纹。**"
        )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 工具 6：拓扑投影前端大屏（安全级）
# ═══════════════════════════════════════════════════════════

@registry.register(
    name="visualize_topology",
    description="向工作台前端下发渲染机房 2D 物理拓扑结构的视觉指令大屏组件，并在界面上高亮隐患点。当用户要求直观展示或画图时调用本工具。此调用不对话，仅输出渲染成功信号。",
    parameters={
        "type": "object",
        "properties": {
            "zone": {"type": "string", "description": "展示哪个区域的物理机房地图，如 'A区'、'B区' 或 'all'"},
            "danger_racks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "需要红色高亮告警的危险隐患机柜列表，如 ['RACK-A02']",
            },
        },
        "required": ["zone", "danger_racks"],
    },
    risk_level=RiskLevel.SAFE,
)
def visualize_topology(zone: str = "all", danger_racks: list = None) -> str:
    if danger_racks is None:
        danger_racks = []
    racks_str = ", ".join(danger_racks) if danger_racks else "无"
    return f"✨ 已成功唤起前端拓扑渲染引擎，直观展现物理机房 {zone} 的隐患节点分布图 ({racks_str})。"
