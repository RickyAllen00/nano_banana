import os
import json
import base64
from datetime import datetime
from io import BytesIO

import streamlit as st
from PIL import Image

# Optional: load local .env for local dev; on Streamlit Cloud, use st.secrets
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# ---- Config ----
st.set_page_config(page_title="Nano Banana - Streamlit Demo", layout="wide")

# API Key resolution (Streamlit Cloud -> Env)
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY", None) or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
if not GOOGLE_API_KEY:
    st.error("未检测到 GOOGLE_API_KEY（或 GEMINI_API_KEY）。请在 Streamlit Secrets 或环境变量中配置后重试。")

# Database URL: recommend a hosted Postgres for persistence on Streamlit Cloud
DATABASE_URL = st.secrets.get("DATABASE_URL", None) or os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # fallback to local sqlite for local development
    db_path = os.path.join(os.path.dirname(__file__), "app.db")
    DATABASE_URL = f"sqlite:///{db_path}"

# ---- DB Layer (SQLAlchemy Core) ----
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, Text, DateTime
from sqlalchemy.sql import select, insert, desc

@st.cache_resource(show_spinner=False)
def get_engine():
    return create_engine(DATABASE_URL, future=True)

@st.cache_resource(show_spinner=False)
def init_db():
    engine = get_engine()
    meta = MetaData()
    generations = Table(
        "demo_generations", meta,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("prompt", Text, nullable=False),
        Column("images", Text, nullable=False),  # JSON array of data URLs
        Column("created_at", DateTime, nullable=False),
    )
    meta.create_all(engine)
    return engine, generations

engine, T_generations = init_db()

# ---- Google GenAI Client ----
from google import genai

@st.cache_resource(show_spinner=False)
def get_genai_client(api_key: str):
    return genai.Client(api_key=api_key)

client = get_genai_client(GOOGLE_API_KEY) if GOOGLE_API_KEY else None

# ---- Generation Logic ----
def parse_images_from_response(response):
    """Extract PNG bytes list from Google GenAI response."""
    results = []
    try:
        candidates = getattr(response, 'candidates', []) or []
        for cand in candidates:
            parts = getattr(cand.content, 'parts', []) or []
            for part in parts:
                inline = getattr(part, 'inline_data', None)
                if inline and getattr(inline, 'data', None):
                    data_bytes = inline.data
                    if isinstance(data_bytes, bytes):
                        results.append(data_bytes)
                    else:
                        # Some versions might return bytearray/memoryview
                        try:
                            results.append(bytes(data_bytes))
                        except Exception:
                            pass
    except Exception:
        pass
    return results

def image_bytes_to_data_url(img_bytes: bytes, mime: str = "image/png") -> str:
    b64 = base64.b64encode(img_bytes).decode()
    return f"data:{mime};base64,{b64}"

def generate_images(prompt: str, count: int):
    if not client:
        raise RuntimeError("GenAI 客户端尚未初始化：缺少 API Key")
    images = []
    for _ in range(max(1, count)):
        response = client.models.generate_content(
            model="gemini-2.5-flash-image-preview",
            contents=[prompt],
        )
        imgs = parse_images_from_response(response)
        if not imgs:
            # 降级处理：无图时跳过
            continue
        # 取第一张
        images.append(imgs[0])
    return images

# ---- Persistence helpers ----
@st.cache_data(show_spinner=False)
def load_history(limit: int = 50):
    with engine.connect() as conn:
        stmt = select(T_generations).order_by(desc(T_generations.c.id)).limit(limit)
        rows = conn.execute(stmt).mappings().all()
        return [dict(r) for r in rows]

@st.cache_data(show_spinner=False)
def get_entry(entry_id: int):
    with engine.connect() as conn:
        stmt = select(T_generations).where(T_generations.c.id == entry_id)
        row = conn.execute(stmt).mappings().first()
        return dict(row) if row else None

def save_generation(prompt: str, data_urls: list[str]):
    with engine.begin() as conn:
        conn.execute(
            insert(T_generations),
            {
                "prompt": prompt,
                "images": json.dumps(data_urls, ensure_ascii=False),
                "created_at": datetime.utcnow(),
            },
        )
    # 清除缓存的历史
    load_history.clear()

# ---- UI helpers ----
from uuid import uuid4
import streamlit.components.v1 as components

def copy_button_component(data_url: str, label: str = "复制图片"):
    from string import Template
    btn_id = f"copy-btn-{uuid4().hex}"
    tmpl = Template(
        """
<div style='display:inline-block;margin-left:6px;'>
  <button id="$btn_id" style='padding:6px 10px;border-radius:6px;border:1px solid #ddd;cursor:pointer;background:#f7f7f8;'>
    $label
  </button>
</div>
<script>
  (function(){
    const btn = document.getElementById('$btn_id');
    if(!btn) return;
    btn.addEventListener('click', async () => {
      const url = $data_url;
      try {
        const resp = await fetch(url);
        const blob = await resp.blob();
        await navigator.clipboard.write([ new ClipboardItem({ [blob.type]: blob }) ]);
        alert('图片已复制到剪贴板');
      } catch(e) {
        try {
          await navigator.clipboard.writeText(url);
          alert('已复制图片链接');
        } catch(err) {
          alert('复制失败');
        }
      }
    });
  })();
</script>
"""
    )
    html = tmpl.substitute(
        btn_id=btn_id,
        label=label,
        data_url=json.dumps(data_url),
    )
    components.html(html, height=40)

# ---- Sidebar: Settings & History ----
st.sidebar.header("设置")
img_count = st.sidebar.slider("生成图片数量", 1, 4, 1)

st.sidebar.header("历史记录")
hist = load_history()
if hist:
    items = [f"#{h['id']} | {h['prompt'][:24]}... | {h['created_at']}" for h in hist]
    selected = st.sidebar.selectbox("选择一条记录查看", options=["(不选择)"] + items, index=0)
    if selected != "(不选择)":
        sel_id = int(selected.split("|")[0].strip().replace("#", ""))
        entry = get_entry(sel_id)
        if entry:
            st.sidebar.success(f"已选择记录 #{entry['id']}")
            st.session_state["selected_entry"] = entry
else:
    st.sidebar.info("暂无历史记录")

# ---- Main ----
st.title("Nano Banana - Streamlit Demo")
prompt = st.text_area("请输入生成图片的提示词", height=120, placeholder="例如：一幅具有科幻风格的纳米香蕉在高级餐厅的图片")
col_run, col_sp = st.columns([1, 5])
with col_run:
    run = st.button("生成")

if run:
    if not prompt.strip():
        st.warning("请输入提示词")
    elif not GOOGLE_API_KEY:
        st.error("缺少 API Key，请在 Secrets/Env 中配置 GOOGLE_API_KEY。")
    else:
        with st.spinner("生成中，请稍候..."):
            try:
                images_bytes = generate_images(prompt.strip(), img_count)
                if not images_bytes:
                    st.error("未生成到图片，请调整提示词或稍后重试。")
                else:
                    data_urls = [image_bytes_to_data_url(b) for b in images_bytes]
                    save_generation(prompt.strip(), data_urls)
                    st.success("生成成功，已保存到历史记录。")
                    st.session_state["last_result"] = {"prompt": prompt.strip(), "images": data_urls}
            except Exception as e:
                st.error(f"生成失败：{e}")

# Display current selection or last result
result = st.session_state.get("selected_entry") or st.session_state.get("last_result")
if result:
    images = result["images"] if isinstance(result["images"], list) else json.loads(result["images"])  # entry vs last_result
    st.subheader("生成结果")

    # Grid display
    cols = st.columns(min(4, len(images))) if images else []
    for i, data_url in enumerate(images):
        c = cols[i % len(cols)] if cols else st
        with c:
            # Show image
            st.image(data_url, use_container_width=True)
            # Action row: download + copy
            # Convert data_url to raw bytes for download_button
            try:
                header, b64 = data_url.split(",", 1)
                raw = base64.b64decode(b64)
            except Exception:
                raw = None
            fname = f"generated_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{i+1}.png"
            dcol1, dcol2 = st.columns([1,1])
            with dcol1:
                st.download_button("下载图片", data=raw or data_url, file_name=fname, mime="image/png")
            with dcol2:
                copy_button_component(data_url, label="复制图片")

    # Clear selected entry after showing (optional)
    st.session_state["selected_entry"] = None
else:
    st.info("输入提示词并点击“生成”开始，或从左侧选择一条历史记录查看。")