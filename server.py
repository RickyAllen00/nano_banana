import os
import base64
import json
import sqlite3
import secrets
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import List, Optional
import logging
from logging.handlers import TimedRotatingFileHandler
import time

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from google.genai import types, errors
from fastapi.responses import FileResponse
from threading import Semaphore, Lock

# Load environment variables
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing API key. Please set GOOGLE_API_KEY or GEMINI_API_KEY in your .env or environment.")

# Initialize client
client = genai.Client(api_key=API_KEY)

# FastAPI app
app = FastAPI(title="Nano Banana Image Hub", description="Proxy endpoints for Gemini image generation and editing")
# Allow origins from environment (comma-separated), fallback to localhost dev ports
_origins_env = os.getenv("ALLOWED_ORIGINS")
if _origins_env:
    ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]
else:
    ALLOWED_ORIGINS = [
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================
# Auth & DB Utilities
# =====================
BASE_DIR = os.path.dirname(__file__)
# Allow overriding DB path via environment for cloud persistent disks
DB_PATH = os.getenv("DB_PATH") or os.path.join(BASE_DIR, "app.db")
# Ensure DB directory exists and is writable; fallback to /tmp if not
_parent = os.path.dirname(DB_PATH) or BASE_DIR
try:
    os.makedirs(_parent, exist_ok=True)
    _probe = os.path.join(_parent, ".db_write_probe")
    with open(_probe, "w") as f:
        f.write("ok")
    os.remove(_probe)
except Exception as e:
    logging.warning(f"DB dir not writable: {_parent}. Fallback to /tmp/app.db. Reason: {e}")
    DB_PATH = os.path.join("/tmp", "app.db")
    os.makedirs("/tmp", exist_ok=True)
SESSION_COOKIE = "session"
SESSION_TTL_DAYS = 7

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL, -- 'user' | 'assistant'
            type TEXT NOT NULL, -- 'generate' | 'edit'
            prompt TEXT,
            images_json TEXT,
            texts_json TEXT,
            params_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id)
        );
        """
    )
    conn.commit()
    conn.close()

init_db()

# 设置按日滚动日志，保留7天
BASE_DIR = os.path.dirname(__file__)
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logger = logging.getLogger("app")
logger.setLevel(logging.INFO)
if not any(isinstance(h, TimedRotatingFileHandler) for h in logger.handlers):
    _handler = TimedRotatingFileHandler(os.path.join(LOG_DIR, "app.log"), when="midnight", backupCount=7, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_handler)

# password hashing (PBKDF2)
_DEF_ITER = 120_000
_DEF_ALG = "sha256"

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac(_DEF_ALG, password.encode(), salt, _DEF_ITER)
    return f"{salt.hex()}${_DEF_ITER}${_DEF_ALG}${dk.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, iters_s, alg, hash_hex = stored.split("$")
        iters = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        target = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac(alg, password.encode(), salt, iters)
        return hmac.compare_digest(dk, target)
    except Exception:
        return False

# session helpers

def create_session(user_id: int) -> str:
    sid = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    expires = now + timedelta(days=SESSION_TTL_DAYS)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions(session_id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (sid, user_id, now.isoformat(), expires.isoformat()),
        )
    return sid

def delete_session(session_id: str):
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))

def get_current_user_id(request: Request) -> Optional[int]:
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    with get_db() as conn:
        row = conn.execute("SELECT user_id, expires_at FROM sessions WHERE session_id=?", (sid,)).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
            # expire
            conn.execute("DELETE FROM sessions WHERE session_id=?", (sid,))
            return None
        return int(row["user_id"])

# =====================
# API Schemas
# =====================
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL") or "gemini-2.5-flash-image-preview"
GENAI_MAX_RETRIES = int(os.getenv("GENAI_MAX_RETRIES", "2"))
GENAI_BACKOFF_MS = int(os.getenv("GENAI_BACKOFF_MS", "250"))
GENAI_FORCE_SINGLE_ON_RETRY = os.getenv("GENAI_FORCE_SINGLE_ON_RETRY", "1") == "1"
GENAI_MAX_CONCURRENT = int(os.getenv("GENAI_MAX_CONCURRENT", "2"))
GENAI_MIN_INTERVAL_MS = int(os.getenv("GENAI_MIN_INTERVAL_MS", "300"))

# Simple process-wide throttle to avoid tripping upstream rate limits under cloud concurrency
_throttle_sem = Semaphore(GENAI_MAX_CONCURRENT)
_ts_lock = Lock()
_last_call_ts = 0.0

class GenerateRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    # Optional generation parameters
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    candidate_count: Optional[int] = None
    seed: Optional[int] = None
    max_output_tokens: Optional[int] = None
    # conversation
    conv_id: Optional[int] = None

class GenerateResponse(BaseModel):
    images: List[str] = []  # base64 strings
    texts: List[str] = []

@app.get("/health")
async def health():
    return {"status": "ok"}

# Serve frontend index
@app.get("/")
async def index_page():
    index_path = os.path.join(os.path.dirname(__file__), "public", "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)

# =====================
# Auth endpoints
# =====================
class AuthRequest(BaseModel):
    username: str
    password: str

@app.post("/auth/signup")
async def signup(payload: AuthRequest, response: Response):
    with get_db() as conn:
        cur = conn.execute("SELECT id FROM users WHERE username=?", (payload.username,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="用户名已存在")
        conn.execute(
            "INSERT INTO users(username, password_hash, created_at) VALUES (?, ?, ?)",
            (payload.username, hash_password(payload.password), datetime.utcnow().isoformat()),
        )
        user_id = conn.execute("SELECT id FROM users WHERE username=?", (payload.username,)).fetchone()[0]
    sid = create_session(user_id)
    response.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return {"id": user_id, "username": payload.username}

@app.post("/auth/login")
async def login(payload: AuthRequest, response: Response):
    with get_db() as conn:
        row = conn.execute("SELECT id, password_hash FROM users WHERE username=?", (payload.username,)).fetchone()
        if not row or not verify_password(payload.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        user_id = int(row["id"])
    sid = create_session(user_id)
    response.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return {"id": user_id, "username": payload.username}

@app.post("/auth/logout")
async def logout(request: Request, response: Response):
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        delete_session(sid)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}

@app.get("/me")
async def me(request: Request):
    uid = get_current_user_id(request)
    if not uid:
        return {"authenticated": False}
    with get_db() as conn:
        row = conn.execute("SELECT id, username, created_at FROM users WHERE id=?", (uid,)).fetchone()
    return {"authenticated": True, "id": row["id"], "username": row["username"], "created_at": row["created_at"]}

# =====================
# Conversation endpoints
# =====================
class CreateConvRequest(BaseModel):
    title: Optional[str] = None

@app.post("/conversations")
async def create_conversation(payload: CreateConvRequest, request: Request):
    uid = get_current_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    title = payload.title or "新的会话"
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute("INSERT INTO conversations(user_id, title, created_at) VALUES (?, ?, ?)", (uid, title, now))
        conv_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()[0]
    logger.info(f"create_conversation uid={uid} conv_id={conv_id} title='{title}'")
    return {"id": conv_id, "title": title, "created_at": now}

@app.get("/conversations")
async def list_conversations(request: Request):
    uid = get_current_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at FROM conversations WHERE user_id=? ORDER BY id DESC",
            (uid,),
        ).fetchall()
    return [dict(r) for r in rows]

@app.get("/conversations/{conv_id}/messages")
async def list_messages(conv_id: int, request: Request):
    uid = get_current_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    with get_db() as conn:
        owner = conn.execute("SELECT user_id FROM conversations WHERE id=?", (conv_id,)).fetchone()
        if not owner or int(owner["user_id"]) != uid:
            raise HTTPException(status_code=404, detail="会话不存在")
        rows = conn.execute(
            "SELECT role, type, prompt, images_json, texts_json, params_json, created_at FROM messages WHERE conversation_id=? ORDER BY id ASC",
            (conv_id,),
        ).fetchall()
    result = []
    for r in rows:
        result.append({
            "role": r["role"],
            "type": r["type"],
            "prompt": r["prompt"],
            "images": json.loads(r["images_json"]) if r["images_json"] else [],
            "texts": json.loads(r["texts_json"]) if r["texts_json"] else [],
            "params": json.loads(r["params_json"]) if r["params_json"] else {},
            "created_at": r["created_at"],
        })
    return result

@app.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: int, request: Request):
    uid = get_current_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    with get_db() as conn:
        owner = conn.execute("SELECT user_id FROM conversations WHERE id=?", (conv_id,)).fetchone()
        if not owner or int(owner["user_id"]) != uid:
            raise HTTPException(status_code=404, detail="会话不存在")
        conn.execute("DELETE FROM messages WHERE conversation_id=?", (conv_id,))
        conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
    return {"ok": True}

class UpdateConvRequest(BaseModel):
    title: Optional[str] = None

@app.patch("/conversations/{conv_id}")
async def update_conversation(conv_id: int, payload: UpdateConvRequest, request: Request):
    uid = get_current_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    with get_db() as conn:
        owner = conn.execute("SELECT user_id FROM conversations WHERE id=?", (conv_id,)).fetchone()
        if not owner or int(owner["user_id"]) != uid:
            raise HTTPException(status_code=404, detail="会话不存在")
        conn.execute("UPDATE conversations SET title=? WHERE id=?", (title, conv_id))
        row = conn.execute("SELECT id, title, created_at FROM conversations WHERE id=?", (conv_id,)).fetchone()
    logger.info(f"update_conversation uid={uid} conv_id={conv_id} title='{title}'")
    return {"id": row["id"], "title": row["title"], "created_at": row["created_at"]}

# helper to record messages

def _record_turn(conv_id: int, type_: str, prompt: str, images: List[str], texts: List[str], params: dict):
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages(conversation_id, role, type, prompt, images_json, texts_json, params_json, created_at) VALUES (?, 'user', ?, ?, NULL, NULL, ?, ?)",
            (conv_id, type_, prompt, json.dumps(params or {}), now),
        )
        conn.execute(
            "INSERT INTO messages(conversation_id, role, type, prompt, images_json, texts_json, params_json, created_at) VALUES (?, 'assistant', ?, NULL, ?, ?, ?, ?)",
            (conv_id, type_, json.dumps(images or []), json.dumps(texts or []), json.dumps(params or {}), now),
        )

def _genai_call_with_retry(model: str, contents: List, cfg_kwargs: dict):
    cc = cfg_kwargs.get("candidate_count") or 1
    attempt = 0
    last_err: Optional[Exception] = None
    retry_after_s = max(1, int((GENAI_BACKOFF_MS / 1000.0) * (2 ** max(0, GENAI_MAX_RETRIES - 1))))

    # Acquire concurrency gate
    acquired = _throttle_sem.acquire(timeout=30)
    if not acquired:
        logger.warning(f"throttle_sem_timeout model={model} cc={cc}")
        raise HTTPException(status_code=429, detail="服务端限流触发，请稍后重试。", headers={"Retry-After": str(retry_after_s)})
    try:
        # Respect minimal interval between upstream calls
        with _ts_lock:
            now = time.monotonic()
            min_gap = GENAI_MIN_INTERVAL_MS / 1000.0
            wait_s = max(0.0, min_gap - (now - _last_call_ts))
        if wait_s > 0:
            time.sleep(wait_s)
        with _ts_lock:
            # Update last call timestamp just before making upstream call
            globals()["_last_call_ts"] = time.monotonic()

        while attempt <= GENAI_MAX_RETRIES:
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        temperature=cfg_kwargs.get("temperature"),
                        top_p=cfg_kwargs.get("top_p"),
                        top_k=cfg_kwargs.get("top_k"),
                        candidate_count=cc,
                        seed=cfg_kwargs.get("seed"),
                        max_output_tokens=cfg_kwargs.get("max_output_tokens"),
                    ),
                )
                return resp
            except errors.ClientError as e:
                status = getattr(e, "status_code", None)
                msg = str(e)
                if status == 429 or "RESOURCE_EXHAUSTED" in msg or "rate" in msg.lower():
                    last_err = e
                    logger.warning(f"upstream_429 model={model} cc={cc} attempt={attempt} msg={msg}")
                    if attempt == GENAI_MAX_RETRIES:
                        break
                    backoff = (GENAI_BACKOFF_MS / 1000.0) * (2 ** attempt)
                    time.sleep(backoff)
                    if GENAI_FORCE_SINGLE_ON_RETRY and cc > 1:
                        cc = 1
                    attempt += 1
                    continue
                else:
                    raise
            except Exception as e:
                last_err = e
                logger.exception(f"upstream_call_failed model={model} cc={cc} attempt={attempt}: {e}")
                break
    finally:
        _throttle_sem.release()

    raise HTTPException(status_code=429, detail=f"上游配额或速率限制：{last_err}", headers={"Retry-After": str(retry_after_s)})

@app.post("/v1/generate", response_model=GenerateResponse)
async def generate_image(payload: GenerateRequest, request: Request):
    model = payload.model or DEFAULT_MODEL
    logger.info(f"/v1/generate model={model} conv_id={payload.conv_id}")
    # Clamp candidate_count to safe bounds [1,6]
    cc = (payload.candidate_count or 1)
    try:
        cc = max(1, min(6, int(cc)))
    except Exception:
        cc = 1
    cfg_kwargs = {
        "temperature": payload.temperature,
        "top_p": payload.top_p,
        "top_k": payload.top_k,
        "candidate_count": cc,
        "seed": payload.seed,
        "max_output_tokens": payload.max_output_tokens,
    }
    try:
        response = _genai_call_with_retry(model=model, contents=[payload.prompt], cfg_kwargs=cfg_kwargs)
    except HTTPException:
        # Already mapped (e.g., 429)
        raise
    except Exception as e:
        logger.exception(f"/v1/generate failed: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    images: List[str] = []
    texts: List[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        for part in getattr(candidate.content, "parts", []) or []:
            if getattr(part, "inline_data", None) and getattr(part.inline_data, "data", None):
                images.append(base64.b64encode(part.inline_data.data).decode("utf-8"))
            elif getattr(part, "text", None):
                texts.append(part.text)
    if not images and not texts:
        logger.warning("/v1/generate returned no content")
        raise HTTPException(status_code=502, detail="Model returned no content. Try adjusting the prompt.")

    # persist if logged in and conv provided
    uid = get_current_user_id(request)
    if uid and payload.conv_id:
        with get_db() as conn:
            owner = conn.execute("SELECT user_id FROM conversations WHERE id=?", (payload.conv_id,)).fetchone()
            if owner and int(owner["user_id"]) == uid:
                params = {
                    "temperature": payload.temperature,
                    "top_p": payload.top_p,
                    "top_k": payload.top_k,
                    "candidate_count": payload.candidate_count,
                    "seed": payload.seed,
                    "max_output_tokens": payload.max_output_tokens,
                    "model": model,
                }
                _record_turn(payload.conv_id, "generate", payload.prompt, images, texts, params)

    logger.info(f"/v1/generate ok images={len(images)} texts={len(texts)}")
    return GenerateResponse(images=images, texts=texts)

@app.post("/v1/edit", response_model=GenerateResponse)
async def edit_image(
    request: Request,
    prompt: str = Form(...),
    model: Optional[str] = Form(None),
    files: List[UploadFile] = File(..., description="One or more images to edit/compose"),
    temperature: Optional[float] = Form(None),
    top_p: Optional[float] = Form(None),
    top_k: Optional[int] = Form(None),
    candidate_count: Optional[int] = Form(None),
    seed: Optional[int] = Form(None),
    max_output_tokens: Optional[int] = Form(None),
    conv_id: Optional[int] = Form(None),
):
    if not files:
        raise HTTPException(status_code=400, detail="No image files uploaded")

    logger.info(f"/v1/edit files={len(files)} prompt_len={len(prompt) if prompt else 0} conv_id={conv_id}")

    parts: List[types.Part] = []
    for f in files:
        content = await f.read()
        mime = f.content_type or "image/png"
        try:
            parts.append(types.Part.from_bytes(data=content, mime_type=mime))
        except Exception as e:
            logger.warning(f"Invalid image input for {f.filename}: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid image input for {f.filename}: {e}")

    parts.append(prompt)

    # Clamp candidate_count to safe bounds [1,6]
    _cc = (candidate_count or 1)
    try:
        _cc = max(1, min(6, int(_cc)))
    except Exception:
        _cc = 1
    cfg_kwargs = {
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "candidate_count": _cc,
        "seed": seed,
        "max_output_tokens": max_output_tokens,
    }
    try:
        response = _genai_call_with_retry(model=(model or DEFAULT_MODEL), contents=parts, cfg_kwargs=cfg_kwargs)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"/v1/edit failed: {e}")
        raise HTTPException(status_code=500, detail=f"Edit failed: {e}")

    images: List[str] = []
    texts: List[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        for part in getattr(candidate.content, "parts", []) or []:
            if getattr(part, "inline_data", None) and getattr(part.inline_data, "data", None):
                images.append(base64.b64encode(part.inline_data.data).decode("utf-8"))
            elif getattr(part, "text", None):
                texts.append(part.text)

    if not images and not texts:
        logger.warning("/v1/edit returned no content")
        raise HTTPException(status_code=502, detail="Model returned no content. Try adjusting the prompt or inputs.")

    # persist if logged in and conv provided
    uid = get_current_user_id(request)
    params = {
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "candidate_count": candidate_count,
        "seed": seed,
        "max_output_tokens": max_output_tokens,
        "model": model,
    }
    if uid and conv_id:
        with get_db() as conn:
            owner = conn.execute("SELECT user_id FROM conversations WHERE id=?", (conv_id,)).fetchone()
            if owner and int(owner["user_id"]) == uid:
                _record_turn(conv_id, "edit", prompt, images, texts, params)

    logger.info(f"/v1/edit ok images={len(images)} texts={len(texts)}")
    return GenerateResponse(images=images, texts=texts)

# Alias for multi-image composition (same behavior as edit)
@app.post("/v1/compose", response_model=GenerateResponse)
async def compose_images(
    prompt: str = Form(...),
    model: Optional[str] = Form(None),
    files: List[UploadFile] = File(..., description="Two or more images to compose/style transfer"),
):
    return await edit_image(request=request, prompt=prompt, model=model, files=files)

# 请求日志中间件
@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)
        client = request.client.host if request.client else "-"
        logger.info(f"{client} {request.method} {request.url.path} {response.status_code} {duration_ms}ms")
        return response
    except Exception as e:
        duration_ms = int((time.perf_counter() - start) * 1000)
        client = request.client.host if request.client else "-"
        logger.exception(f"{client} {request.method} {request.url.path} ERROR after {duration_ms}ms: {e}")
        raise

# Optional: entry point when running directly: uvicorn server:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)