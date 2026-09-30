# ==============================================================================
# 金枢 (Jin-Shu OS) - 生产级多智能体调度引擎 Dockerfile
# ==============================================================================

FROM python:3.11-slim

# 设置工作目录与环境变量
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PORT=8000

# 安装基础系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖定义并安装
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY . .

# 暴露服务端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# 启动服务
CMD ["uvicorn", "main_v2:app", "--host", "0.0.0.0", "--port", "8000"]
