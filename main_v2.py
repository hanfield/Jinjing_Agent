"""
金枢 (Jin-Shu) - 最终版 FastAPI 后端 (含完整认证体系)
============================================================
定位：纯咨询/建议型平台，不执行任何自动操作。

API 接口：
  POST /api/register         - 注册新操作员
  POST /api/login            - 登录获取 JWT Token
  GET  /api/me               - 获取当前登录用户信息
  GET  /api/alerts           - 从监控数据中检测当前告警
  GET  /api/history          - 获取历史方案记录
  POST /api/chat/stream      - 流式对话（NDJSON），并自动归档方案
  GET  /                     - 跳转 Web 界面
"""

import os
import json
import uuid
import sqlite3
import hashlib
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import AsyncGenerator, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.core import multi_agent_orchestrator
from engine.services.monitoring import monitoring_service


load_dotenv()

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
HISTORY_PATH = os.path.join(os.path.dirname(__file__), "data", "solution_history.json")
DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "datacenter_mock.json")
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "users.db")

# JWT 密钥（首次运行时自动生成并固定）
JWT_SECRET_FILE = os.path.join(os.path.dirname(__file__), "data", ".jwt_secret")
if os.path.exists(JWT_SECRET_FILE):
    with open(JWT_SECRET_FILE, "r") as f:
        JWT_SECRET = f.read().strip()
else:
    JWT_SECRET = secrets.token_hex(32)
    os.makedirs(os.path.dirname(JWT_SECRET_FILE), exist_ok=True)
    with open(JWT_SECRET_FILE, "w") as f:
        f.write(JWT_SECRET)

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72  # Token 有效期 3 天

engine = multi_agent_orchestrator


# ── SQLite 用户数据库初始化 ───────────────────────────────


def init_db():
    """创建用户表（如果不存在）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT DEFAULT '值班员',
            created_at TEXT NOT NULL
        )
    """
    )
    conn.commit()
    conn.close()


def hash_password(password: str) -> str:
    """使用 SHA-256 + 盐值哈希密码"""
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${hashed}"


def verify_password(password: str, stored_hash: str) -> bool:
    """校验密码"""
    salt, hashed = stored_hash.split("$")
    return hashlib.sha256((salt + password).encode()).hexdigest() == hashed


def create_jwt(user_id: str, username: str, display_name: str, role: str) -> str:
    """生成 JWT Token"""
    import jwt

    payload = {
        "sub": user_id,
        "username": username,
        "display_name": display_name,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    """解码并验证 JWT Token"""
    import jwt

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token 已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的认证令牌")


# ── 认证依赖注入 ─────────────────────────────────────────


async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """从请求头中提取并验证 JWT，返回用户信息"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供认证令牌，请先登录")
    token = authorization.split(" ", 1)[1]
    return decode_jwt(token)


# ── 历史记录读写 ──────────────────────────────────────────


def load_history():
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_to_history(
    session_id: str,
    question: str,
    solution: str,
    trigger: str = "用户主动咨询",
    operator: str = "",
    messages: list = None,
    trace: list = None,
):
    history = load_history()

    # 查找是否已有此会话
    existing_session = next((s for s in history if s.get("session_id") == session_id), None)

    turn_data = {
        "question": question,
        "solution": solution,
        "trace": trace or [],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    if existing_session:
        existing_session["turns"].append(turn_data)
        existing_session["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if messages:
            existing_session["full_messages"] = messages
        # 移到最前
        history.remove(existing_session)
        history.insert(0, existing_session)
    else:
        new_session = {
            "session_id": session_id,
            "title": question[:30] + "..." if len(question) > 30 else question,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trigger": trigger,
            "operator": operator,
            "full_messages": messages or [],
            "turns": [turn_data],
        }
        history.insert(0, new_session)

    history = history[:50]
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    return existing_session or new_session


# ── 告警检测已迁移至 engine/monitoring.py (Unified Alert Bus) ──

# ── 应用初始化 ────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # 确保用户数据库已就绪
    print("=" * 60)
    print("🔷 金枢 Jin-Shu · 智能运维咨询平台 已启动")
    print("   模式：咨询建议型（不执行操作）")
    print(f"   认证：SQLite + JWT（{JWT_EXPIRE_HOURS}h 有效期）")
    print(f"   Web UI: http://localhost:{os.getenv('PORT', 8000)}/")
    print("=" * 60)
    yield
    await engine.close()


app = FastAPI(title="金枢 Jin-Shu 智能运维咨询平台", version="4.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

if os.path.exists(STATIC_DIR):
    app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="static")


# ── 请求模型 ─────────────────────────────────────────────


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    message: str
    trigger: str = ""
    chat_session_id: str = "default-session"


class ActionRequest(BaseModel):
    session_id: str
    approved: bool
    trigger: str = ""
    chat_session_id: str = "default-session"


# ── 认证路由 ─────────────────────────────────────────────


@app.post("/api/register")
def register_user(req: RegisterRequest):
    """注册新操作员"""
    if len(req.username) < 2:
        raise HTTPException(status_code=400, detail="工号长度至少 2 个字符")
    if len(req.password) < 4:
        raise HTTPException(status_code=400, detail="密码长度至少 4 个字符")

    display_name = req.display_name or req.username

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 检查用户是否已存在
    cursor.execute("SELECT id FROM users WHERE username = ?", (req.username,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=409, detail="该工号已被注册")

    user_id = f"op-{uuid.uuid4().hex[:8]}"
    password_hash = hash_password(req.password)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        "INSERT INTO users (id, username, password_hash, display_name, role, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, req.username, password_hash, display_name, "值班员", created_at),
    )
    conn.commit()
    conn.close()

    # 自动签发 token
    token = create_jwt(user_id, req.username, display_name, "值班员")

    return {
        "success": True,
        "message": "注册成功，欢迎加入金枢指挥中心",
        "token": token,
        "user": {"id": user_id, "username": req.username, "display_name": display_name, "role": "值班员"},
    }


@app.post("/api/login")
def login_user(req: LoginRequest):
    """操作员登录"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, password_hash, display_name, role FROM users WHERE username = ?", (req.username,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="工号不存在")

    user_id, username, password_hash, display_name, role = row

    if not verify_password(req.password, password_hash):
        raise HTTPException(status_code=401, detail="密码错误")

    token = create_jwt(user_id, username, display_name, role)

    return {
        "success": True,
        "message": f"欢迎回来，{display_name}",
        "token": token,
        "user": {"id": user_id, "username": username, "display_name": display_name, "role": role},
    }


@app.get("/api/me")
def get_me(user: dict = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return {"id": user["sub"], "username": user["username"], "display_name": user["display_name"], "role": user["role"]}


# ── 业务路由（需登录） ───────────────────────────────────


@app.get("/")
def redirect_to_ui():
    return RedirectResponse(url="/ui/")


@app.get("/api/datacenters")
def get_datacenters(user: dict = Depends(get_current_user)):
    """返回所有机房的汇总列表（含告警状态）"""
    return {"datacenters": monitoring_service.get_datacenters()}


@app.get("/api/alerts")
def get_alerts(dc_id: str = None, user: dict = Depends(get_current_user)):
    """检测并返回告警列表，可按 dc_id 过滤；不传则返回所有机房汇总"""
    return {
        "alerts": monitoring_service.get_alerts(dc_id=dc_id),
        "dc_id": dc_id,
        "checked_at": datetime.now().strftime("%H:%M:%S"),
    }


@app.post("/api/alerts/resolve")
def resolve_alert(payload: dict, user: dict = Depends(get_current_user)):
    """
    运维人员手动标记告警已解决：将底层 mock 数据中对应设备状态恢复正常。
    payload: { "alert_id": "DC-BJ-SJS:RACK-A02" }
    """
    alert_id: str = payload.get("alert_id", "")
    if not alert_id or ":" not in alert_id:
        raise HTTPException(status_code=400, detail="无效的 alert_id 格式，应为 dc_id:device_id")

    dc_id_val, device_id = alert_id.split(":", 1)

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据读取失败: {e}")

    matched = False
    for dc in data.get("datacenters", []):
        if dc["id"] != dc_id_val:
            continue

        # 1. 机柜降温
        for rack in dc.get("racks", []):
            if rack["id"] == device_id:
                rack["temp_celsius"] = 24.0
                rack["status"] = "正常"
                matched = True

        # 2. UPS 负载恢复
        for ups in dc.get("ups", []):
            if ups["id"] == device_id:
                ups["load_percent"] = 50
                matched = True

        # 3. HVAC 故障恢复
        for hvac in dc.get("hvac", []):
            if hvac["id"] == device_id:
                hvac["status"] = "运行"
                hvac["return_temp"] = 22.0
                matched = True

        # 4. 服务器状态恢复
        for svr in dc.get("servers", []):
            if svr["id"] == device_id:
                svr["status"] = "正常"
                svr["cpu_percent"] = 30
                svr["mem_percent"] = 40
                matched = True

        # 5. 安防告警解除（sec-001 为特殊 ID）
        if device_id == "sec-001":
            dc["access_log"] = [
                e for e in dc.get("access_log", []) if not (e.get("type") == "外部人员" and e.get("action") == "进入")
            ]
            matched = True

    if not matched:
        raise HTTPException(status_code=404, detail=f"未找到设备 {alert_id}，无法销警")

    try:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据写入失败: {e}")

    return {
        "success": True,
        "message": f"告警 [{alert_id}] 已由 [{user['display_name']}] 标记解决，设备状态已复位",
        "resolved_by": user["display_name"],
        "resolved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/api/topology")
def get_topology(dc_id: str = None, user: dict = Depends(get_current_user)):
    """返回用于三维空间渲染的拓扑数据，按 dc_id 过滤单机房"""
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"nodes": [], "links": [], "dc_id": dc_id}

    datacenters = data.get("datacenters", [])
    if dc_id:
        datacenters = [dc for dc in datacenters if dc["id"] == dc_id]

    nodes = []
    links = []

    for dc in datacenters:
        dc_id_val = dc["id"]
        dc_name = dc["name"]

        for rack in dc.get("racks", []):
            load_rate = rack["power_kw"] / rack["max_capacity_kw"]
            nodes.append(
                {
                    "id": f"{dc_id_val}:{rack['id']}",
                    "raw_id": rack["id"],
                    "type": "rack",
                    "dc_id": dc_id_val,
                    "dc_name": dc_name,
                    "zone": rack["zone"],
                    "floor": rack["floor"],
                    "row": rack.get("row", 1),
                    "col": rack.get("col", 1),
                    "status": rack["status"],
                    "temp": rack["temp_celsius"],
                    "load_rate": round(load_rate, 2),
                    "devices": rack.get("devices", []),
                }
            )
        for ups in dc.get("ups", []):
            nodes.append(
                {
                    "id": f"{dc_id_val}:{ups['id']}",
                    "raw_id": ups["id"],
                    "type": "ups",
                    "dc_id": dc_id_val,
                    "dc_name": dc_name,
                    "zone": ups["zone"],
                    "status": ups["status"],
                    "load_percent": ups["load_percent"],
                    "battery_percent": ups["battery_percent"],
                }
            )
        for hvac in dc.get("hvac", []):
            nodes.append(
                {
                    "id": f"{dc_id_val}:{hvac['id']}",
                    "raw_id": hvac["id"],
                    "type": "hvac",
                    "dc_id": dc_id_val,
                    "dc_name": dc_name,
                    "zone": hvac["zone"],
                    "status": hvac["status"],
                    "supply_temp": hvac["supply_temp"],
                    "return_temp": hvac["return_temp"],
                }
            )

        for server in dc.get("servers", []):
            rack_id = server.get("rack_id")
            if rack_id:
                links.append(
                    {
                        "source": f"{dc_id_val}:{server['id']}",
                        "target": f"{dc_id_val}:{rack_id}",
                        "type": "compute_to_rack",
                    }
                )
        for rack in dc.get("racks", []):
            zone = rack["zone"]
            zone_ups = next((u["id"] for u in dc.get("ups", []) if u["zone"] == zone), None)
            zone_hvac = next((h["id"] for h in dc.get("hvac", []) if h["zone"] == zone), None)
            if zone_ups:
                links.append(
                    {"source": f"{dc_id_val}:{rack['id']}", "target": f"{dc_id_val}:{zone_ups}", "type": "rack_to_ups"}
                )
            if zone_hvac:
                links.append(
                    {
                        "source": f"{dc_id_val}:{rack['id']}",
                        "target": f"{dc_id_val}:{zone_hvac}",
                        "type": "rack_to_hvac",
                    }
                )

    return {"nodes": nodes, "links": links, "dc_id": dc_id, "fetched_at": datetime.now().strftime("%H:%M:%S")}


@app.get("/api/history")
def get_history(user: dict = Depends(get_current_user)):
    """返回历史方案记录"""
    return {"records": load_history()}


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, user: dict = Depends(get_current_user)):
    """
    流式对话接口。
    - 现在根据 chat_session_id 加载全量上下文历史。
    """
    operator_name = user.get("display_name", "未知操作员")
    full_response = []
    final_messages = []

    # 获取现有历史上下文
    history_records = load_history()
    session_data = next((s for s in history_records if s.get("session_id") == req.chat_session_id), None)
    existing_messages = session_data.get("full_messages", []) if session_data else None

    async def generator() -> AsyncGenerator[str, None]:
        nonlocal final_messages
        turn_trace = []
        try:
            async for event_obj in engine.run_stream(req.message, override_messages=existing_messages):
                if event_obj.get("event") == "final_chunk":
                    full_response.append(event_obj["text"])
                elif event_obj.get("event") == "history_update":
                    final_messages = event_obj["messages"]
                    continue

                # 记录推理轨迹
                turn_trace.append(event_obj)
                yield json.dumps(event_obj, ensure_ascii=False) + "\n"
        except Exception as e:
            yield json.dumps({"event": "error", "error": str(e)}, ensure_ascii=False) + "\n"
            return

        full_text = "".join(full_response)
        record = save_to_history(
            session_id=req.chat_session_id,
            question=req.message,
            solution=full_text,
            trigger=req.trigger,
            operator=operator_name,
            messages=final_messages,
            trace=turn_trace,
        )
        yield json.dumps({"event": "done", "record": record}, ensure_ascii=False) + "\n"

    return StreamingResponse(generator(), media_type="application/x-ndjson")


@app.post("/api/chat/action")
async def chat_action(req: ActionRequest, user: dict = Depends(get_current_user)):
    """
    接受用户前台拦截或授权反馈，无缝接续后台大模型的数据流
    """
    operator_name = user.get("display_name", "未知操作员")
    full_response = []
    final_messages = []

    async def generator() -> AsyncGenerator[str, None]:
        nonlocal final_messages
        turn_trace = []
        try:
            async for event_obj in engine.resume_stream(req.session_id, req.approved):
                if event_obj.get("event") == "final_chunk":
                    full_response.append(event_obj.get("text", ""))
                elif event_obj.get("event") == "history_update":
                    final_messages = event_obj["messages"]
                    continue

                turn_trace.append(event_obj)
                yield json.dumps(event_obj, ensure_ascii=False) + "\n"
        except Exception as e:
            yield json.dumps({"event": "error", "error": str(e)}, ensure_ascii=False) + "\n"
            return

        full_text = "".join(full_response)
        action_mark = "✔ 授权执行" if req.approved else "✖ 拒绝执行"
        record = save_to_history(
            session_id=req.chat_session_id,
            question=f"[系统拦截干预] 用户{action_mark}",
            solution=full_text,
            trigger=req.trigger,
            operator=operator_name,
            messages=final_messages,
            trace=turn_trace,
        )
        yield json.dumps({"event": "done", "record": record}, ensure_ascii=False) + "\n"

    return StreamingResponse(generator(), media_type="application/x-ndjson")


@app.post("/api/chat/clear")
async def clear_chat(user: dict = Depends(get_current_user)):
    """
    清除当前大模型的上下文历史，开启新对话
    (现在由前端生成新 Session ID 实现隔离)
    """
    return {"status": "ok", "message": "会话已重置"}


# ── 启动入口 ─────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main_v2:app", host="0.0.0.0", port=port, reload=False)
