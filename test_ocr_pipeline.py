# -*- coding: utf-8 -*-
"""复刻 question_bank_app.ocr_image_to_latex 的请求链路，用于离线验证 OCR 功能。"""
import os, io, base64, sys, json

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"), override=True)

import requests
from PIL import Image

API_KEY = os.getenv("AI_API_KEY")
BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
MODEL = os.getenv("AI_MODEL_NAME", "gpt-4o")

ocr_prompt_file = os.path.join(ROOT, "ocr_prompt.txt")
prompt = os.getenv("AI_OCR_PROMPT", "")
if os.path.exists(ocr_prompt_file):
    with open(ocr_prompt_file, "r", encoding="utf-8") as f:
        prompt = f.read()
prompt = (
    "你是 OCR 转写助手。你只需要把图片中的内容逐字逐符号转写成 LaTeX 源码。\n"
    "禁止解题、禁止推理、禁止补全缺失步骤、禁止生成答案与解析。\n"
    "如果图片里本身包含答案/解析/提示，请原样转写；否则不要凭空生成。\n\n"
    + (prompt or "")
)

def normalize_chat_completions_url(url: str) -> str:
    if "/v1" not in url and "/chat/completions" not in url:
        url = url.rstrip("/") + "/v1"
    if "/chat/completions" not in url:
        url = url.rstrip("/") + "/chat/completions"
    return url

img_path = os.path.join(ROOT, "test_ocr_question.png")
img = Image.open(img_path)
max_image_size = 1024
if max(img.size) > max_image_size:
    ratio = max_image_size / max(img.size)
    img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)), Image.Resampling.LANCZOS)
buffered = io.BytesIO()
img = img.convert("RGB")
img.save(buffered, format="JPEG", quality=80)
b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

payload = {
    "model": MODEL,
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
    ]}],
    "max_tokens": 4096,
}
headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
url = normalize_chat_completions_url(BASE_URL)
print(f"[TEST] model={MODEL}\n[TEST] url={url}\n[TEST] image={img.size}, jpeg_bytes={len(buffered.getvalue())}")
resp = requests.post(url, headers=headers, json=payload, timeout=180)
print(f"[TEST] http_status={resp.status_code}")
if resp.status_code != 200:
    print("[TEST] FAILED:", resp.text[:500])
    sys.exit(1)
result = resp.json()
content = result["choices"][0]["message"]["content"]
print("[TEST] OCR_RESULT_START")
print(content)
print("[TEST] OCR_RESULT_END")
