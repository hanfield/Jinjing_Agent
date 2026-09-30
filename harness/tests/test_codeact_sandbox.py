from engine.tools.codeact_sandbox import execute_python_codeact


def test_codeact_math_and_print():
    code = """
temps = [24.5, 28.0, 31.5, 33.0]
avg = sum(temps) / len(temps)
print(f"平均机柜温度: {avg:.2f}°C")
max_delta = max(temps) - min(temps)
"""
    result = execute_python_codeact(code)
    assert "CodeAct 动态执行结果" in result
    assert "平均机柜温度: 29.25°C" in result
    assert "max_delta=8.5" in result


def test_codeact_security_guardrail():
    # 试图导入 os 系统模块应被静态阻断
    danger_code = """
import os
os.system("echo hacked")
"""
    result = execute_python_codeact(danger_code)
    assert "安全策略阻断" in result
    assert "import os" in result


def test_codeact_timeout_termination():
    # 模拟死循环代码
    infinite_code = """
i = 0
while True:
    i += 1
"""
    result = execute_python_codeact(infinite_code, timeout_seconds=1)
    assert "执行超时" in result
