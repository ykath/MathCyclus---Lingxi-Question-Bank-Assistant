#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MathEx 家长版 · 知识点树服务（M1-T03 底层）

知识点来源：
1. 内置高中数学板块清单（与 ocr_prompt.txt 的板块约束一致）
2. 本地 chapters/ 目录名（如果存在真实题库目录）
家长在「设置」页可增删自定义知识点。
"""
import os

from services.database_service import get_setting, set_setting

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAPTERS_DIR = os.path.join(BASE_DIR, "chapters")

# 与 ocr_prompt.txt【2.5 板块】保持一致
BUILTIN_KNOWLEDGE_POINTS = [
    "集合", "复数", "不等式", "函数", "导数", "三角函数", "解三角形",
    "数列", "向量", "立体几何", "解析几何", "圆锥曲线", "概率", "统计",
    "排列组合", "线性规划", "数论", "命题与逻辑", "流程框图",
]

_SETTING_KEY = "knowledge_points"


def init_knowledge_points() -> list[str]:
    """初始化知识点清单：内置清单 ∪ chapters/ 目录名，写入 app_setting（幂等）。"""
    existing = get_setting(_SETTING_KEY)
    if existing:
        return existing

    points = list(BUILTIN_KNOWLEDGE_POINTS)
    if os.path.isdir(CHAPTERS_DIR):
        for name in sorted(os.listdir(CHAPTERS_DIR)):
            full = os.path.join(CHAPTERS_DIR, name)
            if os.path.isdir(full) and name not in points:
                points.append(name)
    set_setting(_SETTING_KEY, points)
    return points


def get_knowledge_points() -> list[str]:
    return init_knowledge_points()


def add_knowledge_point(name: str) -> list[str]:
    name = (name or "").strip()
    points = init_knowledge_points()
    if name and name not in points:
        points.append(name)
        set_setting(_SETTING_KEY, points)
    return points


def remove_knowledge_point(name: str) -> list[str]:
    points = [p for p in init_knowledge_points() if p != name]
    set_setting(_SETTING_KEY, points)
    return points
