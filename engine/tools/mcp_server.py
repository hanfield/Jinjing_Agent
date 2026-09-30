import argparse
import json
import sys
import traceback

from engine.tools import registry


def main():
    parser = argparse.ArgumentParser(
        description="Jinjing Agent Worker MCP Server"
    )
    parser.add_argument(
        "--worker",
        type=str,
        required=True,
        help="Worker ID (e.g., L2_Infra, L2_Cloud, L2_Sec)",
    )
    args = parser.parse_args()

    # 定义每个 Worker 允许的专属工具集
    allowed_tools_map = {
        "L2_Infra": [
            "query_infrastructure",
            "query_k8s_metrics",
            "analyze_cooling",
            "analyze_dynamic_baseline",
            "predict_load_by_traffic",
            "fingerprint_early_warning",
            "visualize_topology",
            "analyze_thermal_infrared_matrix",
            "execute_python_codeact",
            "explore_hypothesis_tree",
        ],
        "L2_Cloud": [
            "query_infrastructure",
            "query_k8s_metrics",
            "scale_k8s_deployment",
            "resolve_spatial_topology",
            "execute_remote_command",
            "restart_server",
            "record_expert_experience",
            "execute_python_codeact",
            "explore_hypothesis_tree",
        ],
        "L2_Sec": [
            "analyze_security",
            "query_infrastructure",
            "inspect_visual_patrol_frame",
        ],
    }

    allowed_tools = allowed_tools_map.get(args.worker, [])

    # 过滤工具注册表，只保留允许的工具
    worker_tools = {}
    for name in allowed_tools:
        t = registry.get_tool(name)
        if t:
            worker_tools[name] = t

    sys.stderr.write(
        f"[MCP Server] Starting MCP Server for {args.worker} with {len(worker_tools)} tools\n"
    )
    sys.stderr.flush()

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break

            req = json.loads(line.strip())
            method = req.get("method")
            req_id = req.get("id")

            if method == "initialize":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {
                            "name": f"Jinjing-{args.worker}-MCP",
                            "version": "1.0",
                        },
                    },
                }
            elif method == "tools/list":
                tools_list = []
                for name, t in worker_tools.items():
                    tools_list.append(
                        {
                            "name": name,
                            "description": t.description,
                            "inputSchema": t.parameters,
                        }
                    )
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": tools_list},
                }
            elif method == "tools/call":
                params = req.get("params", {})
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})

                if tool_name not in worker_tools:
                    resp = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32601,
                            "message": f"Tool '{tool_name}' not found or not allowed for this worker",
                        },
                    }
                else:
                    try:
                        tool = worker_tools[tool_name]
                        result = str(tool.fn(**tool_args))
                        resp = {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "content": [{"type": "text", "text": result}],
                                "isError": False,
                            },
                        }
                    except Exception as e:
                        resp = {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": f"Error executing tool: {str(e)}",
                                    }
                                ],
                                "isError": True,
                            },
                        }
            elif method == "notifications/initialized":
                continue
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method '{method}' not found",
                    },
                }

            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        except Exception:
            sys.stderr.write(f"[MCP Server Error] {traceback.format_exc()}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
