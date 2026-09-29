"""
金枢 2.0 (Jin-Shu OS) - Environment Proxy Harness (透明环境代理沙箱)
====================================================================
企业级沙箱不仅作为被动拦截器，也作为 API 网关模拟器。
支持 Chaos Engineering（注入超时、报错）与动态 Schema 校验。
同时，它提供硬核 Docker 容器级安全隔离执行支撑。
"""

import time
import random
import asyncio
import subprocess
from typing import Dict, Any, List
from engine.blackboard import global_blackboard


class SandboxProxyHarness:
    """透明环境代理沙箱 (硬核隔离与评测流审计)"""

    def __init__(self):
        self.active_state: Dict[str, Any] = {}
        self.intercepted_tool_calls: List[Dict[str, Any]] = []
        self.chaos_config: Dict[str, Any] = {}
        self.use_docker: bool = False

        # 预先检查 Docker 是否可用
        try:
            res = subprocess.run(["docker", "info"], capture_output=True, timeout=2)
            if res.returncode == 0:
                self.use_docker = True
        except Exception:
            pass

    def setup_sandbox(self, state: Dict[str, Any], chaos_config: Dict[str, Any] = None):
        """初始化沙箱注入态，进行容器环境隔离，并设置混沌工程配置"""
        self.active_state = state
        self.intercepted_tool_calls = []
        self.chaos_config = chaos_config or {}
        global_blackboard.reset()
        
        # 将真实状态映射入黑板（兼容老逻辑）
        for rack_id, metrics in self.active_state.get("racks", {}).items():
            global_blackboard.update_environment(
                rack_id=rack_id,
                temp=metrics.get("temp", 25.0),
                load_ratio=metrics.get("load_ratio", 0.5)
            )

        # 如果开启了 Docker 支持，则进行物理隔离容器重置与数据水合
        if self.use_docker:
            self._recreate_docker_sandboxes()

    def _recreate_docker_sandboxes(self):
        """物理重置 Docker 沙箱环境，完成主机级快照水合与隔离"""
        # 1. 清理已有沙箱容器
        try:
            res = subprocess.run(
                ["docker", "ps", "-a", "--filter", "name=jinshu-sandbox-", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=3
            )
            if res.returncode == 0:
                for name in res.stdout.splitlines():
                    if name.startswith("jinshu-sandbox-"):
                        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=3)
        except Exception:
            pass

        # 2. 从任务状态中识别待水合的虚拟机主机，并拉起对应隔离的容器
        # 默认对 SVR-003 以及其它在 racks/servers 中存在的机器进行容器隔离
        servers_to_spawn = ["SVR-003"]
        for rack_id in self.active_state.get("racks", {}).keys():
            if rack_id.startswith("SVR-") or rack_id.startswith("prod-"):
                servers_to_spawn.append(rack_id)

        for svr in set(servers_to_spawn):
            container_name = f"jinshu-sandbox-{svr}"
            try:
                # 运行隔离的 alpine 容器，不映射任何宿主机端口，做纯网络与系统级隔离
                subprocess.run(
                    ["docker", "run", "-d", "--name", container_name, "-h", svr, "alpine", "sleep", "3600"],
                    capture_output=True,
                    timeout=5
                )
                # 容器内文件系统状态数据高保真水合 (Hydration)
                # 创建 /data/logs/nginx 目录与稀疏超大文件 (模拟48GB日志且不占用真实磁盘)
                subprocess.run(["docker", "exec", container_name, "mkdir", "-p", "/data/logs/nginx"], capture_output=True, timeout=3)
                subprocess.run(["docker", "exec", container_name, "truncate", "-s", "48G", "/data/logs/nginx/error.log"], capture_output=True, timeout=3)
                subprocess.run(["docker", "exec", container_name, "touch", "/data/logs/nginx/access.log"], capture_output=True, timeout=3)
                # 创建数据库 ibd 文件 (模拟1GB数据)
                subprocess.run(["docker", "exec", container_name, "mkdir", "-p", "/data/mysql"], capture_output=True, timeout=3)
                subprocess.run(["docker", "exec", container_name, "truncate", "-s", "1G", "/data/mysql/data.ibd"], capture_output=True, timeout=3)
            except Exception:
                pass

    async def execute_simulated_api(self, agent_id: str, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """模拟真实的外部 API 调用，包含拦截与混沌注入"""
        # 记录调用轨迹
        self.record_tool_call(agent_id, tool_name, args)
        
        # 1. 混沌注入：模拟延迟 (Latency Jitter)
        jitter_ms = self.chaos_config.get("latency_jitter_ms", 0)
        if jitter_ms > 0:
            await asyncio.sleep(jitter_ms / 1000.0)
            
        # 2. 混沌注入：模拟失败 (503 Service Unavailable)
        failure_rate = self.chaos_config.get("inject_503_probability", 0.0)
        if failure_rate > 0 and random.random() < failure_rate:
            raise Exception(f"[Sandbox Chaos] 503 Service Unavailable for tool {tool_name}")
            
        # 3. 拦截并返回模拟数据 (Mock API Router)
        if tool_name == "fingerprint_early_warning":
            return {"status": "warning", "details": "Detected thermal anomaly in A02"}
        elif tool_name == "resolve_spatial_topology":
            return {"connected_nodes": ["UPS-A-01", "RACK-A02"]}
        elif tool_name == "restart_server":
            target = args.get("server_id")
            if not target:
                raise ValueError("Missing required argument: server_id")
            return {"status": "success", "message": f"Server {target} reboot initiated."}
        
        # 默认回落
        return {"status": "executed", "mocked": True}

    def record_tool_call(self, agent_id: str, tool_name: str, args: Dict[str, Any]):
        """记录底层工具调用轨迹"""
        self.intercepted_tool_calls.append({
            "agent_id": agent_id,
            "tool_name": tool_name,
            "args": args,
            "timestamp": time.time()
        })
