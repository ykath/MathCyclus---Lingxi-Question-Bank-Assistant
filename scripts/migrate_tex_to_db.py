#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MathEx 家长版 · 旧 .tex 题库迁移脚本（M1-T14）

把 chapters/**/*.tex（content_* 章节索引除外）迁移进 SQLite：
- 解析 Label Data 元数据头 + problem/answer/solutions 环境
- 题干、选项、答案、解析、难度、标签、来源拆分入库
- 写 import_batch（mode=commit, import_type=tex）与逐条 import_report_item
- 迁移报告输出到 reports/migration_report_<时间戳>.md（本地私有目录）

用法：
    python scripts/migrate_tex_to_db.py            # 正式迁移
    python scripts/migrate_tex_to_db.py --dry-run  # 只解析不写库，输出报告
"""
import argparse
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import database_service as db
from services.ocr_service import _PROBLEM_HEADER, _ANSWER_ENV, _SOLUTION_ENV, _extract_choices
from utils.latex_ops import parse_meta_data

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAPTERS_DIR = os.path.join(BASE_DIR, "chapters")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")


def parse_question_tex(content: str) -> dict:
    """解析单个题目 .tex 文件为结构化字段。"""
    meta, clean = parse_meta_data(content)
    header = _PROBLEM_HEADER.search(clean)
    if not header:
        raise ValueError("未找到 \\begin{problem} 环境头")
    meta_info = header.groupdict()

    problem_end = clean.find(r"\end{problem}")
    body = clean[header.end():problem_end if problem_end != -1 else len(clean)]
    stem, choices = _extract_choices(body)

    answer = _ANSWER_ENV.search(clean)
    solutions = _SOLUTION_ENV.findall(clean)
    answer_tex = answer.group("body").strip() if answer else ""
    # 多解析（另解）合并，保留 [另解] 参数标注
    solution_parts = []
    for opt, sbody in solutions:
        sbody = sbody.strip()
        if sbody:
            solution_parts.append(f"【{opt}】\n{sbody}" if opt else sbody)
    solution_tex = "\n\n".join(solution_parts)

    tags = []
    if meta.get("标签"):
        tags = [t.strip() for t in re.split(r"[,，]", meta["标签"]) if t.strip()]
    if not tags and meta_info.get("subject"):
        tags = [t.strip() for t in re.split(r"[,，]", meta_info["subject"]) if t.strip()]

    difficulty = None
    if meta.get("难度星级"):
        try:
            difficulty = max(1, min(5, int(meta["难度星级"])))
        except ValueError:
            difficulty = None

    if choices:
        qtype = "单选题"
    elif answer_tex and not solution_tex:
        qtype = "填空题"
    else:
        qtype = "解答题"

    source = " ".join(x for x in [
        meta_info.get("year"), meta_info.get("paper"),
        f"第{meta_info['num']}题" if meta_info.get("num") else "",
    ] if x).strip()

    return {
        "stem_tex": stem,
        "choices": choices,
        "answer_tex": answer_tex,
        "solution_tex": solution_tex,
        "difficulty": difficulty,
        "tags": tags,
        "note": meta.get("备注", "") or source,
        "question_type_name": qtype,
        "raw_source_tex": content,
        "source": source,
    }


def build_canonical_tex(parsed: dict) -> str:
    parts = [parsed["stem_tex"]]
    if parsed["choices"]:
        parts.append("\\begin{choices}")
        parts.extend(f"\\choice{{{{{c}}}}}" for c in parsed["choices"])
        parts.append("\\end{choices}")
    tex = "\n".join(parts)
    if parsed["answer_tex"]:
        tex += f"\n\\begin{{answer}}\n{parsed['answer_tex']}\n\\end{{answer}}"
    if parsed["solution_tex"]:
        tex += f"\n\\begin{{solutions}}\n{parsed['solution_tex']}\n\\end{{solutions}}"
    return tex


def migrate(dry_run: bool = False) -> dict:
    """执行迁移，返回统计结果并输出 Markdown 报告。"""
    db.ensure_initialized()
    tex_files = []
    for root, _dirs, files in os.walk(CHAPTERS_DIR):
        for name in sorted(files):
            if name.endswith(".tex") and not name.startswith("content_"):
                tex_files.append(os.path.join(root, name))

    results = {"total": len(tex_files), "inserted": 0, "failed": [], "dry_run": dry_run}
    batch_id = None
    if not dry_run and tex_files:
        batch_id = db.create_import_batch("tex", source_path="chapters/",
                                          summary=f"旧题库迁移，共 {len(tex_files)} 个文件")

    qtype_map = {t["name"]: t["question_type_id"] for t in db.list_question_types()}

    for path in tex_files:
        rel = os.path.relpath(path, BASE_DIR)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            parsed = parse_question_tex(content)
            if not parsed["stem_tex"].strip():
                raise ValueError("题干为空")
            if not dry_run:
                qid = db.insert_question({
                    "question_type_id": qtype_map.get(parsed["question_type_name"]),
                    "stem_tex": parsed["stem_tex"],
                    "choices": parsed["choices"],
                    "answer_tex": parsed["answer_tex"],
                    "solution_tex": parsed["solution_tex"],
                    "difficulty": parsed["difficulty"],
                    "tags": parsed["tags"],
                    "note": parsed["note"],
                    "official_flag": 1,
                    "canonical_tex": build_canonical_tex(parsed),
                    "raw_source_tex": parsed["raw_source_tex"],
                    "normalized_status": "normalized",
                }, change_source="migration", note=f"迁移自 {rel}")
                db.add_report_item(batch_id, "inserted", source_file=rel, question_id=qid)
            results["inserted"] += 1
        except Exception as e:  # noqa: BLE001 - 逐题容错，失败进入报告
            results["failed"].append((rel, str(e)))
            if not dry_run:
                db.add_report_item(batch_id, "error", source_file=rel, reason=str(e))

    if batch_id:
        db.finish_import_batch(batch_id,
                               f"成功 {results['inserted']} / 失败 {len(results['failed'])}")

    # 输出迁移报告
    os.makedirs(REPORTS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(REPORTS_DIR, f"migration_report_{stamp}.md")
    lines = [
        f"# 题库迁移报告（{'dry-run' if dry_run else '正式迁移'}）",
        "",
        f"- 时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 扫描目录：chapters/",
        f"- 发现题目文件：{results['total']} 个",
        f"- 成功解析{'并入' if not dry_run else ''}库：{results['inserted']} 个",
        f"- 失败：{len(results['failed'])} 个",
        "",
    ]
    if results["failed"]:
        lines += ["## 失败清单", ""]
        lines += [f"- `{rel}`：{err}" for rel, err in results["failed"]]
    if results["total"] == 0:
        lines += [
            "## 说明",
            "",
            "本地 chapters/ 目录中没有题目文件（仅章节索引 content_*.tex）。",
            "本题库 clone 不包含真实题源（题库文件默认不入 Git）。",
            "当你把题目 .tex 文件放回 chapters/ 对应板块目录后，重新运行本脚本即可迁移。",
        ]
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    results["report_path"] = report_path
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="旧 .tex 题库迁移到 SQLite")
    parser.add_argument("--dry-run", action="store_true", help="只解析不写库")
    args = parser.parse_args()

    results = migrate(dry_run=args.dry_run)
    print(f"[migrate] 扫描到题目文件: {results['total']}")
    print(f"[migrate] 成功: {results['inserted']}  失败: {len(results['failed'])}")
    print(f"[migrate] 报告: {results['report_path']}")
    return 0 if not results["failed"] else 2


if __name__ == "__main__":
    sys.exit(main())
