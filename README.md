# Nano Banana

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
  - `google-genai`、`streamlit`、`sqlalchemy`、`pillow`、`python-dotenv`
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

## 启动 Streamlit 演示
- 命令：`streamlit run streamlit_app.py`
- 首次运行会在项目目录创建（或使用）`app.db`。
- API Key：优先从 `st.secrets['GOOGLE_API_KEY']` 获取，其次读取环境变量 `GOOGLE_API_KEY / GEMINI_API_KEY`。
- 功能：输入提示词生成图片、保存历史、下载与复制图片到剪贴板。

## 独立脚本示例（nano_api.py）
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

生成与编辑：
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
  - 仅文本提示词 → 走 `/v1/generate`。
  - 上传图片 + 文本提示词 → 走 `/v1/edit`（或多图合成）。
- 右侧设置栏可调 `model`、`temperature`、`top_p` 等生成参数。
- 发送区域的“张数”（`candidate_count`）会被后端限制在 1~6。

## 日志与数据
- 后端：`logs/app.log` 按天滚动，保留 7 天。
- 数据库：默认使用本地 SQLite `app.db`；Streamlit 演示支持配置 `DATABASE_URL` 指向 Postgres 等。

## 常见问题（FAQ）
- 提示“缺少 API Key”：请在 `.env` 或系统环境设置 `GOOGLE_API_KEY` 或 `GEMINI_API_KEY`。
- `uvicorn` 未安装：运行后端前执行 `pip install uvicorn`。
- CORS/Cookie 问题：请通过后端地址访问页面（默认 `http://127.0.0.1:8000/`），避免直接用静态端口访问导致 Cookie 失效。
- 模型无内容返回：调整提示词或参数；后端会返回 502 并给出提示。

## 开发提示
- 修改前端后可直接刷新浏览器；后端接口变更需重启（或 `--reload` 热重载）。
- 若要扩展 API，建议沿用当前的 Pydantic 结构与日志记录方式，并考虑在会话内持久化消息以便前端展示。