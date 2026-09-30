from engine.tools.vision_tools import (
    analyze_thermal_infrared_matrix,
    inspect_visual_patrol_frame,
)


def test_thermal_infrared_matrix_analysis():
    # 测试对机柜 A02 垂直热力点阵的解析
    report = analyze_thermal_infrared_matrix("RACK-A02", height_layers=6)
    assert "红外热成像点阵诊断 - RACK-A02" in report
    assert "最高测温点" in report
    assert "垂直梯度差" in report
    assert "U1-U7(底层)" in report
    assert "U36-U42(顶层)" in report


def test_visual_patrol_frame_inspection():
    # 测试机器视觉对机柜门与母线巡查
    report = inspect_visual_patrol_frame("RACK-A02", inspection_item="all")
    assert "机房机器人视觉巡查 - 目标: RACK-A02" in report
    assert "物理柜门侦测" in report
    assert "地板下漏水绳侦测" in report

    # 测试对漏水空调 CRAC-A01 的侦测
    leak_report = inspect_visual_patrol_frame("CRAC-A01", inspection_item="leak_sensor")
    assert "液体反光斑块" in leak_report
