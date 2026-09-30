"""
金枢 3.0 (Jin-Shu OS) - 代码即行动执行沙箱 (CodeAct Dynamic Python Sandbox)
==============================================================================
突破预定义静态工具的表达力边界。当面对复杂的非标准机房日志解析、时序统计回归、
热力学微分方程计算或动态指标多表联查时，允许大模型在受限安全沙箱中动态编写并执行 Python 代码。

安全防护特性：
  1. 严格受限全局命名空间 (Restricted Globals): 屏蔽危险内建函数 (__import__, eval, exec, open)。
  2. 超时看门狗 (Timeout Watchdog): 限制单次代码执行不超过指定时限 (默认 5s)，防止死循环耗尽资源。
  3. 预装载数据中心计算库: 内置 math, re, json, datetime 以及机房当前遥测数据与拓扑图引用。
  4. 标准输入输出重定向: 完整捕获 stdout 与 stderr，实时反馈执行结果给智能体进行自反思。
"""

import json
import subprocess
import sys

from engine.memory.topology_graph import global_topology_graph
from engine.tools.base import RiskLevel, get_dc_data, registry

_SANDBOX_RUNNER = """
import io
import json
import math
import re
import sys
import datetime

# 受限 Builtins 白名单
safe_builtins = {
    k: getattr(__builtins__, k)
    for k in [
        "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
        "format", "int", "isinstance", "issubclass", "len", "list", "map",
        "max", "min", "print", "range", "round", "set", "sorted", "str", "sum",
        "tuple", "zip"
    ]
    if hasattr(__builtins__, k)
}

context_input = json.loads(sys.stdin.read())
user_code = context_input.get("code", "")
dc_data = context_input.get("dc_data", {})
topology = context_input.get("topology", {})

safe_globals = {
    "__builtins__": safe_builtins,
    "math": math,
    "re": re,
    "json": json,
    "datetime": datetime,
    "dc_data": dc_data,
    "topology": topology,
}
safe_locals = {}

stdout_buf = io.StringIO()
sys_stdout = sys.stdout

try:
    sys.stdout = stdout_buf
    compiled = compile(user_code, "<codeact_sandbox>", "exec")
    exec(compiled, safe_globals, safe_locals)
    sys.stdout = sys_stdout

    out_text = stdout_buf.getvalue().strip()
    locs = {k: str(v) for k, v in safe_locals.items() if not k.startswith("_")}
    result = {
        "status": "success",
        "output": out_text if out_text else "✅ 代码执行完成，无标准输出 (无 print 返回)。",
        "locals": locs,
    }
    print(json.dumps(result))
except Exception as e:
    sys.stdout = sys_stdout
    err_result = {
        "status": "error",
        "error": f"{type(e).__name__}: {str(e)}",
    }
    print(json.dumps(err_result))
"""


@registry.register(
    name="execute_python_codeact",
    description="【代码即行动 CodeAct 沙箱】在受限 Python 隔离沙箱中动态运行分析脚本。"
    "专用于处理：非标准文本日志的正则提取、机柜垂直温度梯度的热力学建模计算、"
    "多指标时序序列统计方差分析等复杂临时计算。支持标准 print 输出，预置 math/re/json/dc_data。",
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "要执行的 Python 3 代码文本。通过 print() 输出分析结论或计算结果。",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "最大运行超时时限（秒），默认 5 秒",
                "default": 5,
            },
        },
        "required": ["code"],
    },
    risk_level=RiskLevel.SAFE,
)
def execute_python_codeact(code: str, timeout_seconds: int = 5) -> str:
    """运行 CodeAct Python 沙箱并返回执行捕获输出"""
    # 静态安全语法过滤
    forbidden_tokens = [
        "import os",
        "import sys",
        "import subprocess",
        "__import__",
        "eval(",
        "exec(",
        "open(",
        "shutil",
    ]
    for token in forbidden_tokens:
        if token in code:
            return f"❌ 安全策略阻断: 沙箱代码禁止包含敏感系统调用 '{token}'！请仅使用沙箱内置的数据计算与正则库。"

    dc_data = get_dc_data()
    payload = json.dumps({
        "code": code,
        "dc_data": dc_data,
        "topology": {
            "nodes": list(global_topology_graph.nodes.keys()),
            "nodes_count": len(global_topology_graph.nodes),
        },
    })

    try:
        proc = subprocess.run(
            [sys.executable, "-c", _SANDBOX_RUNNER],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if proc.returncode != 0 and not proc.stdout.strip():
            return f"❌ 运行时错误:\n{proc.stderr.strip()}"

        res = json.loads(proc.stdout.strip())
        if res.get("status") == "success":
            out = res.get("output", "").strip()
            vars_summary = res.get("locals", {})
            vars_str = ", ".join(f"{k}={v}" for k, v in list(vars_summary.items())[:5])
            header = "🐍 【CodeAct 动态执行结果】"
            if vars_str:
                return f"{header}\n{out}\n\n[导出变量状态]: {vars_str}"
            return f"{header}\n{out}"
        else:
            return f"❌ 运行时错误:\n{res.get('error')}"
    except subprocess.TimeoutExpired:
        return f"⏱️ 执行超时: 代码运行超过了最大时限 ({timeout_seconds}s)！请检查是否存在死循环。"
    except Exception as e:
        return f"❌ 沙箱执行异常：{e}"
