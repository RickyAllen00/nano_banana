# Nano Banana

提示：已移除 Streamlit 演示与 Render 部署文件（`streamlit_app.py` 与 `render.yaml`）。如需使用这两者，请从历史提交恢复或在删除前保留本地副本。

一个基于 Google GenAI（Gemini）的图片生成与编辑小应用，后端使用 FastAPI，前端为纯静态页面，另附 Streamlit 演示页面与独立脚本示例。

## 架构概览
- 后端：`FastAPI` 提供健康检查、账号登录注册、会话与消息管理，以及图片生成与图片编辑接口。
- 前端：`public/index.html` 通过浏览器直接调用后端接口，实现“Chat/对话 + 图片上传 + 生成/编辑”的体验。
- 演示：`streamlit_app.py` 使用 Streamlit 搭建演示界面，本地默认使用 SQLite 持久化历史记录。
- 独立脚本：`nano_api.py` 展示如何直接调用 Gemini 接口生成图片并保存到本地。

## 目录结构
- `server.py`：FastAPI 应用与主要接口定义（图片生成、编辑、会话、认证等）。
- `public/index.html`：静态前端页面（直接打开或通过后端 `/` 路由访问）。
- `streamlit_app.py`：Streamlit 演示（图片生成 + 历史记录展示与下载/复制）。
- `nano_api.py`：最小示例脚本（生成单张图片到 `generated_image.png`）。
- `requirements.txt`：项目依赖。
- `logs/`：后端运行日志（按天滚动）。
- `app.db`：本地 SQLite 数据库（后端与 Streamlit 演示均可能使用）。

## 环境依赖
- Python 3.10+（推荐 3.10 或更高）
- 依赖见 `requirements.txt`：
  - `google-genai`、`fastapi`、`python-dotenv`、`python-multipart`
- 运行后端建议安装：`uvicorn`

## 准备工作
1. 创建并激活虚拟环境（Windows 示例）：
   - `python -m venv .venv`
   - `.venv\Scripts\activate`
2. 安装依赖：
   - `pip install -r requirements.txt`
   - 后端启动需安装 `uvicorn`：`pip install uvicorn`
3. 配置环境变量（任选其一）：
   - 在项目根目录创建 `.env`，内容示例：
     - `GOOGLE_API_KEY=你的密钥`
     - 或 `GEMINI_API_KEY=你的密钥`
   - 或在系统环境变量中设置 `GOOGLE_API_KEY`（或 `GEMINI_API_KEY`）。

## 启动后端（FastAPI）
- 方式一：使用 `uvicorn` 命令启动（推荐开发）：
  - `uvicorn server:app --reload --host 0.0.0.0 --port 8000`
- 方式二：直接运行 `server.py`（同样依赖 uvicorn）：
  - `python server.py`
- 启动后访问：`http://127.0.0.1:8000/`
  - 根路径 `/` 会返回 `public/index.html` 前端页面。
  - 如从静态服务器（如 `:5500`）打开 `index.html`，页面会自动跳转到后端地址以确保 Cookie 生效。

<!-- 已移除 Streamlit 演示，若需要可参考历史提交自行恢复 -->

### 云端部署与配额速率提示

- 若在云端（如 Render）调用出现 `429 RESOURCE_EXHAUSTED`，表示上游模型配额或速率限制。
- 后端已支持可配置的指数退避重试与错误码映射（环境变量：`GENAI_MAX_RETRIES`, `GENAI_BACKOFF_MS`, `GENAI_FORCE_SINGLE_ON_RETRY`）。
- 进一步在云端开启服务端限流以规避高并发触发：`GENAI_MAX_CONCURRENT`（默认 2）、`GENAI_MIN_INTERVAL_MS`（默认 300ms）。
- 可通过设置 `DEFAULT_MODEL` 为更轻量的模型变体、将 `candidate_count` 设为 `1` 来降低开销。
- 云端请使用与本地相同的 `GOOGLE_API_KEY` 或 `GEMINI_API_KEY`，并确保放在服务的环境变量中（不要提交到仓库）。
- 云端请使用与本地相同的 `GOOGLE_API_KEY` 或 `GEMINI_API_KEY`，并确保放在服务的环境变量中（不要提交到仓库）。
- API Key：优先从 `st.secrets['GOOGLE_API_KEY']` 获取，其次读取环境变量 `GOOGLE_API_KEY / GEMINI_API_KEY`。
- 首次运行会在项目目录创建（或使用）`app.db`。
- API Key：优先从 `st.secrets['GOOGLE_API_KEY']` 获取，其次读取环境变量 `GOOGLE_API_KEY / GEMINI_API_KEY`。
- 功能：输入提示词生成图片、保存历史、下载与复制图片到剪贴板。

<!-- 已移除 Render 部署配置 render.yaml，如需云端部署可按照 Dockerfile 或自选平台流程进行。 -->
- 403 PERMISSION_DENIED（Requests from referer <empty> are blocked）：
  - 原因：当前 `GOOGLE_API_KEY`/`GEMINI_API_KEY` 在 Google 控制台设置了“应用限制：HTTP 引用者（Website）”。服务端发起的请求 Referer 为空，会被拒绝。
  - 处理：在 Google Cloud Console 或 AI Studio 创建一个“应用限制：None”的服务器端 API Key；仅保留“API 限制：Generative Language API”。将该 Key 配置到云端环境变量（Render 仪表盘）。
- 429 RESOURCE_EXHAUSTED：
  - 可能由模型的每分钟/每天限额触发，或并发突发导致；建议使用闪系列模型（`gemini-1.5-flash` 或 `gemini-2.0-flash-lite`）、将 `candidate_count=1`，并在云端启用 `GENAI_MAX_CONCURRENT / GENAI_MIN_INTERVAL_MS`。
- 403 PERMISSION_DENIED（Requests from referer <empty> are blocked）：
  - 原因：当前 `GOOGLE_API_KEY`/`GEMINI_API_KEY` 在 Google 控制台设置了“应用限制：HTTP 引用者（Website）”。服务端发起的请求 Referer 为空，会被拒绝。
  - 处理：在 Google Cloud Console 或 AI Studio 创建一个“应用限制：None”的服务器端 API Key；仅保留“API 限制：Generative Language API”。将该 Key 配置到云端环境变量（Render 仪表盘）。
- 429 RESOURCE_EXHAUSTED：
  - 可能由模型的每分钟/每天限额触发，或并发突发导致；建议使用闪系列模型（`gemini-1.5-flash` 或 `gemini-2.0-flash-lite`）、将 `candidate_count=1`，并在云端启用 `GENAI_MAX_CONCURRENT / GENAI_MIN_INTERVAL_MS`。

- 必填环境变量：`GOOGLE_API_KEY`（或 `GEMINI_API_KEY`）。
- 可选：`DEFAULT_MODEL`（建议 `gemini-1.5-flash` 或 `gemini-2.0-flash-lite`）。
你可以只部署并使用图片生成/编辑接口，而不启用会话或对话功能。当前后端的生成接口不需要登录；只有在提供 `conv_id` 且用户登录时才会写入历史记录。

<!-- 已移除 Render 推荐部署章节，保留 Docker 与 ngrok/NAS 方案 -->

### HTTP API（仅生成/编辑）
  - 字段：`prompt`、`files`（1 张或多张图片）、以及可选生成参数。
  - Body：`{ prompt, model?, temperature?, top_p?, top_k?, candidate_count?, seed?, max_output_tokens? }`
  - 返回：`{ images: [base64 PNG], texts: [string] }`
  - 说明：`candidate_count` 会被限制在 `1..6`；不需要认证。
- `POST /v1/edit`（multipart/form-data）：
  - 字段：`prompt`、`files`（1 张或多张图片）、以及可选生成参数。
  - 返回：`{ images: [base64 PNG], texts: [string] }`
  - 说明：不需要认证；仅在提供 `conv_id` 且登录时才持久化。

### curl 示例

```bash
    "model": "gemini-1.5-flash",
    "candidate_count": 1
  -d '{
    "prompt": "a yellow banana wearing sunglasses, 4k, photorealistic",
    "model": "gemini-1.5-flash",
    "candidate_count": 1
  }'

  -F "model=gemini-1.5-flash" \
  -H "Accept: application/json" \
  -F "prompt=make the banana purple with neon glow" \
  -F "model=gemini-1.5-flash" \
  -F "files=@./banana.png;type=image/png"
```

### Python 客户端示例

```python
import requests
def generate(prompt: str, model="gemini-1.5-flash"):
BASE = "https://<your-render-domain>"

def generate(prompt: str, model="gemini-1.5-flash"):
    r = requests.post(f"{BASE}/v1/generate", json={
        "model": model,
        "candidate_count": 1,
    }, timeout=60)
    r.raise_for_status()
    data = r.json()
    # 取第一张图片（base64 PNG）
    if data.get("images"):
        img_b64 = data["images"][0]
        with open("out.png", "wb") as f:
            import base64
            f.write(base64.b64decode(img_b64))
def edit(prompt: str, img_path: str, model="gemini-1.5-flash"):

def edit(prompt: str, img_path: str, model="gemini-1.5-flash"):
        data = {"prompt": prompt, "model": model}
        files = {"files": ("image.png", fp, "image/png")}
        data = {"prompt": prompt, "model": model}
        r = requests.post(f"{BASE}/v1/edit", files=files, data=data, timeout=120)
        r.raise_for_status()
        return r.json()

print(generate("a minimal banana logo in flat style"))
```

### 生产建议
- 显式设置 `DEFAULT_MODEL` 为闪系列，控制 `candidate_count=1` 初始验证。
- 在云端启用上述限流与重试环境变量，降低突发并发导致的 429 概率。
- 无需会话/历史时，不传 `conv_id`；认证端点与会话端点可忽略。

- 行为：调用 Gemini 模型，生成一张图片并保存为 `generated_image.png`，若响应包含文本也会打印到终端。
- 命令：`python nano_api.py`
- 行为：调用 Gemini 模型，生成一张图片并保存为 `generated_image.png`，若响应包含文本也会打印到终端。

## HTTP API（精简说明）
后端主要路由（详见 `server.py`）：
- `GET /health`：健康检查。
- `GET /`：返回前端页面 `public/index.html`。

认证与用户：
- `POST /auth/signup`：注册，Body：`{username, password}`；成功后设置会话 Cookie。
- `POST /auth/login`：登录，Body：`{username, password}`；成功后设置会话 Cookie。
- `POST /auth/logout`：登出，清除会话 Cookie。
- `GET /me`：当前登录状态与用户信息。

会话与消息：
- `POST /conversations`：创建会话，Body（可选）：`{title}`。
- `GET /conversations`：获取当前用户的会话列表。
- `GET /conversations/{conv_id}/messages`：获取指定会话的消息历史。
- `PATCH /conversations/{conv_id}`：更新标题。
- `DELETE /conversations/{conv_id}`：删除会话。

  - Body：`{ prompt, model?, temperature?, top_p?, top_k?, candidate_count?, seed?, max_output_tokens?, conv_id? }`
- `POST /v1/generate`（JSON）：
  - Body：`{ prompt, model?, temperature?, top_p?, top_k?, candidate_count?, seed?, max_output_tokens?, conv_id? }`
  - 返回：`{ images: [base64 PNG], texts: [string] }`
  - 说明：`candidate_count` 会被限制到 `1..6` 范围。
- `POST /v1/edit`（multipart/form-data）：
  - 字段：`prompt`、`files`（1 张或多张图片）、以及上述可选生成参数。
  - 返回：`{ images: [base64 PNG], texts: [string] }`
  - 若提供 `conv_id` 且用户已登录，会将本次结果追加到会话中。
- `POST /v1/compose`：同 `edit`，用于多图风格迁移/合成（至少两张图片）。

## 前端使用说明
- 页面顶部可登录/注册；登录后可创建与管理会话。
- 中部聊天区域支持：
- 右侧设置栏可调 `model`、`temperature`、`top_p` 等生成参数。
  - 上传图片 + 文本提示词 → 走 `/v1/edit`（或多图合成）。
- 右侧设置栏可调 `model`、`temperature`、`top_p` 等生成参数。
- 发送区域的“张数”（`candidate_count`）会被后端限制在 1~6。

## 日志与数据
- 后端：`logs/app.log` 按天滚动，保留 7 天。
- 数据库：默认使用本地 SQLite `app.db`；Streamlit 演示支持配置 `DATABASE_URL` 指向 Postgres 等。
- 提示“缺少 API Key”：请在 `.env` 或系统环境设置 `GOOGLE_API_KEY` 或 `GEMINI_API_KEY`。
## 常见问题（FAQ）
- 提示“缺少 API Key”：请在 `.env` 或系统环境设置 `GOOGLE_API_KEY` 或 `GEMINI_API_KEY`。
- `uvicorn` 未安装：运行后端前执行 `pip install uvicorn`。
- CORS/Cookie 问题：请通过后端地址访问页面（默认 `http://127.0.0.1:8000/`），避免直接用静态端口访问导致 Cookie 失效。
- 模型无内容返回：调整提示词或参数；后端会返回 502 并给出提示。

## 开发提示
- 修改前端后可直接刷新浏览器；后端接口变更需重启（或 `--reload` 热重载）。
- 若要扩展 API，建议沿用当前的 Pydantic 结构与日志记录方式，并考虑在会话内持久化消息以便前端展示。
## NAS + Docker + ngrok 快速映射公网地址

如果你有一台 NAS（如群晖/Synology），可以使用 Docker + ngrok 将后端快速暴露到公网用于内测体验。

### 前提
- 注册 ngrok 账号并获取 `NGROK_AUTHTOKEN`。
- 在 NAS 上安装 Docker（或启用 Docker 套件）。

### 步骤（推荐使用 docker compose）
1. 在项目根目录创建 `.env`，写入：
   - `GOOGLE_API_KEY=你的服务端API密钥`（或 `GEMINI_API_KEY`）
   - `NGROK_AUTHTOKEN=你的ngrok令牌`
   - 可选：`DEFAULT_MODEL=gemini-1.5-flash`，以及 `GENAI_MAX_CONCURRENT=1`、`GENAI_MIN_INTERVAL_MS=500`。
2. 启动：
   - `docker compose -f docker-compose.ngrok.yml up -d`
3. 查看公网地址：
   - `docker logs -f ngrok-tunnel`，日志中会显示 `Forwarding https://xxxx.ngrok.io -> api:8000`。
4. 验证：
   - `curl https://xxxx.ngrok.io/health`
   - `curl -X POST https://xxxx.ngrok.io/v1/generate -H "Content-Type: application/json" -d '{"prompt":"a yellow banana","model":"gemini-1.5-flash","candidate_count":1}'`

> 提示：`docker-compose.ngrok.yml` 已包含持久化卷 `/data` 用于 SQLite；如仅做无状态体验，可忽略数据库持久化。

### 安全与额度建议
- 使用“服务器端 API Key”（应用限制为 None，仅限制到 Generative Language API）；避免 Referer 限制导致 403。
- 在云端/公网环境建议开启服务端限流与重试（见上文环境变量），并控制 `candidate_count=1`。
- 如需额外保护，可在隧道前增加 Basic Auth（通过反向代理如 Caddy/Nginx 实现），或使用 IP 白名单。

### 可替代方案
- Cloudflare Tunnel：免端口映射，配置自定义域更方便。可在 NAS 上安装 `cloudflared`，命令示例：
  - `cloudflared tunnel --url http://127.0.0.1:8000`（或在 Compose 内指向 `api:8000`）。
  - 需要登录 Cloudflare 账号并在后台设置域名与隧道。
- Tailscale Funnel：在装有 Tailscale 的机器上启用 Funnel 暴露本地端口，适合个人/小团队快速分享。
- Railway/Fly.io：与 Render 类似的“一键部署 + 公网域名”平台，可直接使用本仓库的 Dockerfile。
## NAS + 节点小宝内网穿透部署（4041 端口）

适合已有 NAS 并安装了“节点小宝”的场景，通过 Docker 在 NAS 上运行服务并由“节点小宝”将 4041 端口穿透到公网。

### 准备
- 在项目根目录创建 `.env`：
  - `GOOGLE_API_KEY=你的服务端API密钥`（或 `GEMINI_API_KEY`）
  - 可选：`DEFAULT_MODEL=gemini-1.5-flash`、`GENAI_MAX_CONCURRENT=1`、`GENAI_MIN_INTERVAL_MS=500`
- 注意：`.env` 中的 `NGROK_AUTHTOKEN` 与本方案无关（给 ngrok 使用），可留空。

### 在 NAS 上启动到 4041 端口
- 运行：`docker compose -f docker-compose.nas.yml up -d`
- 查看容器：`docker ps`（确认 `nano-banana-api` 映射为 `0.0.0.0:4041->8000/tcp`）
- 局域网自测：`curl http://<NAS内网IP>:4041/health`

### 在“节点小宝”配置内网穿透
- 新建 HTTP 穿透服务：
  - 本地目标：`http://<NAS内网IP>:4041`
  - 路由路径：`/`（根路径透传，避免子路径导致接口 404）
  - 健康检查：`/health`（周期探测，便于监控）
  - Host 头：保持原样（或开启保留 Host 选项），避免某些代理对主机头处理导致不兼容。
  - TLS：视节点小宝是否支持边缘 TLS 终止；如开启 HTTPS，确保反向代理到后端为 HTTP。
- 保存并启用后，记下公网访问域名，例如：`https://your-node-xiaobao-domain/...`

### 公网验证
- 访问健康检查：`curl https://<你的公网域名>/health`
- 生成接口：
  - `curl -X POST https://<你的公网域名>/v1/generate -H "Content-Type: application/json" -d '{"prompt":"a yellow banana","model":"gemini-1.5-flash","candidate_count":1}'`

### 常见问题
- 403 PERMISSION_DENIED（Referer 为空被拒绝）：请使用“服务器端 API Key”（应用限制 None，仅限制到 Generative Language API）。
- 429 RESOURCE_EXHAUSTED：降低并发与候选数，启用服务端限流与指数退避（见上文环境变量）。
- 子路径穿透导致 404：请将节点小宝的路径设置为 `/` 并直通转发，不要增加额外前缀。