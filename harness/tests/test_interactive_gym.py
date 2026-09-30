import pytest
from harness.environments.sandbox_proxy import SandboxProxyHarness


@pytest.mark.asyncio
async def test_interactive_gym_thermodynamics():
    sandbox = SandboxProxyHarness()
    sandbox.setup_sandbox({
        "racks": {
            "RACK-A02": {"temp": 29.5, "load_ratio": 0.8}
        },
        "servers": {
            "SVR-001": {"status": "OVERHEATING", "cpu_load": 0.85}
        }
    })

    # 1. 触发指纹告警
    fp_res = await sandbox.execute_simulated_api("L2_Infra", "fingerprint_early_warning", {})
    assert fp_res["status"] == "warning"
    assert fp_res["target"] == "RACK-A02"

    # 2. 模拟制冷调频，机柜温度应下降
    cool_res = await sandbox.execute_simulated_api("L2_Infra", "analyze_cooling", {})
    assert cool_res["status"] == "success"
    # 初始 29.5，降温 2.8 应该为 26.7
    assert sandbox.active_state["racks"]["RACK-A02"]["temp"] < 29.5

    # 3. 模拟服务器重启与负载释放
    reboot_res = await sandbox.execute_simulated_api("L2_Cloud", "restart_server", {"server_id": "SVR-001"})
    assert reboot_res["status"] == "success"
    assert sandbox.active_state["servers"]["SVR-001"]["status"] == "REBOOTED_HEALTHY"
    assert sandbox.active_state["servers"]["SVR-001"]["cpu_load"] == 0.05
