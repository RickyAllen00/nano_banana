import os
import sys
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image
from io import BytesIO

# 加载 .env 并获取 API Key（兼容 GOOGLE_API_KEY / GEMINI_API_KEY）
load_dotenv()
api_key = os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')
if not api_key:
    print('未检测到 API Key，请在 .env 中设置 GOOGLE_API_KEY 或 GEMINI_API_KEY 后重试。')
    sys.exit(1)

# 初始化客户端
client = genai.Client(api_key=api_key)

# 文本生成图像的提示
prompt = (
    "Create a picture of a nano banana dish in a fancy restaurant with a Gemini theme"
)

# 生成内容
response = client.models.generate_content(
    model="gemini-2.5-flash-image-preview",
    contents=[prompt],
)

# 解析返回并保存图片
script_dir = os.path.dirname(__file__)
output_path = os.path.join(script_dir, 'generated_image.png')
saved = False
for candidate in getattr(response, 'candidates', []) or []:
    for part in getattr(candidate.content, 'parts', []) or []:
        if getattr(part, 'inline_data', None) and getattr(part.inline_data, 'data', None):
            image = Image.open(BytesIO(part.inline_data.data))
            image.save(output_path)
            saved = True
            print(f"已生成图像：{output_path}")
        elif getattr(part, 'text', None):
            # 输出可能的文本说明
            print(part.text)

if not saved:
    print('未在响应中找到图像数据。请调整提示词或检查模型与配额。')