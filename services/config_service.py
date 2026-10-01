#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MathEx 家长版 · 本地配置服务（M1-T02 底层）

配置优先级：data/config.json（界面配置） > .env（兜底） > 内置默认值。
data/ 目录已被 .gitignore 保护，配置不会进入 Git。
"""
import json
import os
import threading

from dotenv import load_dotenv

_LOCK = threading.Lock()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")

DEFAULT_CONFIG = {
    # AI 服务
    "ai_api_key": "",
    "ai_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "ai_model_name": "qwen-vl-plus",
    # 首启向导
    "wizard_completed": False,
    "child_grade": "",           # 如「高一」「高二」
    "textbook_version": "",      # 如「人教 A 版（2019）」
    # 录入偏好
    "default_difficulty": 3,
}


def _load_env_fallback() -> dict:
    """从 .env 读取兜底配置（热加载，允许用户改 .env 后生效）。"""
    load_dotenv(ENV_PATH, override=True)
    return {
        "ai_api_key": os.getenv("AI_API_KEY", "") or "",
        "ai_base_url": os.getenv("AI_BASE_URL", "") or "",
        "ai_model_name": os.getenv("AI_MODEL_NAME", "") or "",
    }


def load_config() -> dict:
    """读取完整配置：默认值 < .env 兜底 < data/config.json。"""
    config = dict(DEFAULT_CONFIG)
    env = _load_env_fallback()
    for key in ("ai_api_key", "ai_base_url", "ai_model_name"):
        if env.get(key):
            config[key] = env[key]

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                file_config = json.load(f)
            if isinstance(file_config, dict):
                for key, value in file_config.items():
                    if key in DEFAULT_CONFIG and value is not None:
                        config[key] = value
        except (json.JSONDecodeError, OSError):
            # 配置文件损坏时退回默认值，不让应用崩溃
            pass
    return config


def save_config(updates: dict) -> dict:
    """把 updates 写入 data/config.json（只覆盖已知键），返回合并后的完整配置。"""
    with _LOCK:
        config = load_config()
        for key, value in (updates or {}).items():
            if key in DEFAULT_CONFIG:
                config[key] = value
        os.makedirs(DATA_DIR, exist_ok=True)
        temp_path = CONFIG_PATH + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, CONFIG_PATH)
        return config


def mask_api_key(key: str) -> str:
    """API Key 脱敏显示：前 4 位 + *** + 后 2 位。"""
    key = key or ""
    if len(key) <= 6:
        return "***" if key else "（未配置）"
    return f"{key[:4]}***{key[-2:]}"


def ai_is_configured(config: dict | None = None) -> bool:
    config = config or load_config()
    return bool(config.get("ai_api_key"))
