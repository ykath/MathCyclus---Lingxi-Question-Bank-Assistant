# -*- coding: utf-8 -*-
"""
MathEx 家长版 · 打印服务（M3）

双通道：
1. LaTeX 通道（主）：ctexart 家庭练习模板 → xelatex 编译 PDF（题目册 + 答案册分离）
2. 浏览器通道（降级）：自带 KaTeX 的打印友好 HTML，无 LaTeX 环境也能打印

打印设置（settings dict）：
- paper: A4 / A5
- whitespace: 紧凑 / 标准 / 充裕（每题作答留白高度）
- separate_answers: 题答分离（默认开）
- font_size: 标准 / 偏大
- title / with_date / with_name_score：页眉要素
"""
import html
import json
import os
import re
import shutil
import subprocess
from datetime import datetime

from utils.latex_ops import latex_to_markdown

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(BASE_DIR, "exports", "papers")

PRINT_SETTINGS_DEFAULTS = {
    "paper": "A4",
    "whitespace": "标准",
    "separate_answers": True,
    "font_size": "偏大",
    "title": "数学练习",
    "with_date": True,
    "with_name_score": True,
}

WHITESPACE_CM = {"紧凑": 2.5, "标准": 5.0, "充裕": 10.0}


# ------------------------------------------------------------
# 环境检测（M3-T01）
# ------------------------------------------------------------

def xelatex_available() -> bool:
    return shutil.which("xelatex") is not None


# ------------------------------------------------------------
# LaTeX 通道（M3-T04）
# ------------------------------------------------------------

_TEX_PREAMBLE = r"""% MathEx 家庭练习模板（轻量版，独立可编译）
\documentclass[@@PAPER_SIZE@@,@@FONT_SIZE@@]{ctexart}
\usepackage[margin=2cm]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{tasks}
\settasks{label=\Alph*.}
\usepackage{tikz}
\usepackage{lastpage}
\usepackage{fancyhdr}
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\small @@HEADER_LEFT@@}
\fancyhead[R]{\small 第 \thepage 页 / 共 \pageref{LastPage} 页}
\renewcommand{\headrulewidth}{0.4pt}

% 选择题环境（自动按宽度分栏）
\newenvironment{choices}{\begin{tasks}(2)}{\end{tasks}}
\newcommand{\choice}[1]{\task #1}

% 带圈数字
\newcommand{\circled}[1]{\tikz[baseline=(char.base)]{\node[shape=circle,draw,inner sep=1pt] (char) {#1};}}

% 常用数学命令
\providecommand{\dps}{\displaystyle}
\renewcommand{\geq}{\geqslant}
\renewcommand{\ge}{\geqslant}
\renewcommand{\leq}{\leqslant}
\renewcommand{\le}{\leqslant}

\setlength{\parindent}{0pt}
\setlength{\parskip}{6pt}
"""


def _tex_header(settings: dict) -> str:
    paper_size = "a4paper" if settings.get("paper") == "A4" else "a5paper"
    font_size = "12pt" if settings.get("font_size") == "偏大" else "11pt"
    header_left = settings.get("title", "数学练习")
    if settings.get("with_date"):
        header_left += f" · {datetime.now().strftime('%Y年%m月%d日')}"
    return (_TEX_PREAMBLE
            .replace("@@PAPER_SIZE@@", paper_size)
            .replace("@@FONT_SIZE@@", font_size)
            .replace("@@HEADER_LEFT@@", header_left))


def _name_score_line(settings: dict) -> str:
    if not settings.get("with_name_score"):
        return ""
    return (r"\begin{center}\large 姓名：\underline{\hspace{6em}}\hfill "
            r"得分：\underline{\hspace{4em}}\end{center}" + "\n")


def _choices_tex(choices: list) -> str:
    lines = ["\\begin{choices}"]
    lines.extend(f"\\choice{{{{{c}}}}}" for c in choices)
    lines.append("\\end{choices}")
    return "\n".join(lines)


def _question_body_tex(item: dict, number: int, settings: dict) -> str:
    parts = [f"\\section*{{第 {number} 题}}", item.get("stem_tex", "").strip()]
    if item.get("choices"):
        parts.append(_choices_tex(item["choices"]))
    blank = WHITESPACE_CM.get(settings.get("whitespace"), 5.0)
    # 解答题留白加倍
    if not item.get("choices") and settings.get("whitespace") == "充裕":
        blank = 14.0
    parts.append(f"\\vspace{{{blank}cm}}")
    return "\n\n".join(parts)


def _answer_body_tex(item: dict, number: int) -> str:
    parts = [f"\\section*{{第 {number} 题}}"]
    if (item.get("answer_tex") or "").strip():
        parts.append(f"\\textbf{{【答案】}}\n\n{item['answer_tex'].strip()}")
    if (item.get("solution_tex") or "").strip():
        parts.append(f"\\textbf{{【解析】}}\n\n{item['solution_tex'].strip()}")
    if len(parts) == 1:
        parts.append("（本题未录入答案）")
    return "\n\n".join(parts)


def build_print_tex(items: list[dict], settings: dict) -> tuple[str, str]:
    """生成 (题目册 tex, 答案册 tex)。"""
    header = _tex_header(settings)
    title = settings.get("title", "数学练习")

    q_parts = [header, "\\begin{document}",
               f"\\begin{{center}}\\LARGE\\textbf{{{title}}}\\end{{center}}",
               _name_score_line(settings)]
    for i, item in enumerate(items, 1):
        q_parts.append(_question_body_tex(item, i, settings))
    q_parts.append("\\end{document}")

    a_parts = [header, "\\begin{document}",
               f"\\begin{{center}}\\LARGE\\textbf{{{title} · 答案与解析}}\\end{{center}}"]
    for i, item in enumerate(items, 1):
        a_parts.append(_answer_body_tex(item, i))
    a_parts.append("\\end{document}")

    return "\n".join(q_parts), "\n".join(a_parts)


def compile_tex(tex_content: str, out_dir: str, name: str,
                timeout: int = 120) -> tuple[str | None, str]:
    """编译 TeX 为 PDF，返回 (pdf 路径, 错误信息)。xelatex 不存在时只保存 .tex。"""
    os.makedirs(out_dir, exist_ok=True)
    tex_path = os.path.join(out_dir, f"{name}.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex_content)

    if not xelatex_available():
        return None, "NO_XELATEX"

    try:
        for _ in range(2):  # 两遍编译以解析 lastpage 引用
            proc = subprocess.run(
                ["xelatex", "-interaction=nonstopmode", "-output-directory", out_dir, tex_path],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, cwd=out_dir,
            )
        pdf_path = os.path.join(out_dir, f"{name}.pdf")
        if proc.returncode != 0 or not os.path.exists(pdf_path):
            log_tail = (proc.stdout or "")[-800:]
            return None, f"编译失败：{log_tail}"
        return pdf_path, ""
    except subprocess.TimeoutExpired:
        return None, f"编译超时（{timeout}s）"
    except OSError as e:
        return None, f"无法调用 xelatex：{e}"


def generate_print_pdfs(items: list[dict], settings: dict, job_id: int) -> dict:
    """生成打印产物。返回 {dir, question_pdf, answer_pdf, question_tex, answer_tex, errors}。"""
    out_dir = os.path.join(EXPORTS_DIR, f"print_job_{job_id}")
    q_tex, a_tex = build_print_tex(items, settings)

    result = {"dir": out_dir, "errors": []}
    q_pdf, q_err = compile_tex(q_tex, out_dir, "questions")
    result["question_tex"] = os.path.join(out_dir, "questions.tex")
    result["question_pdf"] = q_pdf
    if q_err and q_err != "NO_XELATEX":
        result["errors"].append(f"题目册：{q_err}")

    if settings.get("separate_answers", True):
        a_pdf, a_err = compile_tex(a_tex, out_dir, "answers")
        result["answer_tex"] = os.path.join(out_dir, "answers.tex")
        result["answer_pdf"] = a_pdf
        if a_err and a_err != "NO_XELATEX":
            result["errors"].append(f"答案册：{a_err}")
    else:
        result["answer_pdf"] = None
        result["answer_tex"] = None

    result["no_xelatex"] = not xelatex_available()
    return result


# ------------------------------------------------------------
# 浏览器降级通道（M3-T05）：自带 KaTeX 的打印 HTML
# ------------------------------------------------------------

def _md_lite_to_html(md: str) -> str:
    """把 latex_to_markdown 的输出转为打印 HTML：保留内嵌 HTML/img，转换段落与加粗。"""
    # 表格
    def _table(match):
        rows = [r.strip() for r in match.group(0).strip().split("\n") if r.strip()]
        cells = []
        for idx, row in enumerate(rows):
            if re.match(r"^\|[\s\-|]+\|$", row):
                continue
            tag = "th" if idx == 0 else "td"
            cols = [c.strip() for c in row.strip("|").split("|")]
            cells.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cols) + "</tr>")
        return '<table border="1" cellspacing="0" cellpadding="6">' + "".join(cells) + "</table>"

    md = re.sub(r"(?:^\|.*\|$[\r\n]?)+", _table, md, flags=re.MULTILINE)
    md = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", md, flags=re.DOTALL)
    md = re.sub(r"^###\s+(.+)$", r"<h3>\1</h3>", md, flags=re.MULTILINE)

    # 段落：空行分段，段内换行转 <br>；含块级 HTML 的段落直接透传
    blocks = re.split(r"\n\s*\n", md)
    out = []
    for block in blocks:
        block = block.strip("\n")
        if not block.strip():
            continue
        if re.match(r"^\s*<(div|table|img|h3|blockquote|details)", block):
            out.append(block)
        else:
            out.append("<p>" + block.replace("\n", "<br>") + "</p>")
    return "\n".join(out)


def _item_to_html(item: dict, number: int, settings: dict, with_answer: bool) -> str:
    from app.components.question_render import assemble_tex
    tex = assemble_tex(
        item.get("stem_tex", ""), item.get("choices"),
        item.get("answer_tex", "") if with_answer else "",
        item.get("solution_tex", "") if with_answer else "",
    )
    md = latex_to_markdown(tex, show_title=False)
    body = _md_lite_to_html(md)

    blank = WHITESPACE_CM.get(settings.get("whitespace"), 5.0)
    if not item.get("choices") and settings.get("whitespace") == "充裕":
        blank = 14.0
    blank_html = "" if with_answer else f'<div class="blank" style="height:{blank}cm"></div>'

    return (f'<div class="question"><div class="qnum">第 {number} 题</div>'
            f"{body}{blank_html}</div>")


def generate_print_html(items: list[dict], settings: dict) -> str:
    """生成打印友好的独立 HTML（题目部分 + 答案部分，分页）。"""
    title = html.escape(settings.get("title", "数学练习"))
    font_px = "13pt" if settings.get("font_size") == "偏大" else "11.5pt"
    paper = settings.get("paper", "A4")

    date_line = f' · {datetime.now().strftime("%Y年%m月%d日")}' if settings.get("with_date") else ""
    name_line = ('<div class="name-line">姓名：__________　　得分：__________</div>'
                 if settings.get("with_name_score") else "")

    questions_html = "\n".join(_item_to_html(it, i, settings, with_answer=False)
                               for i, it in enumerate(items, 1))
    answers_html = ""
    if settings.get("separate_answers", True):
        answers_html = ('<div class="page-break"></div>'
                        f"<h1>{title} · 答案与解析</h1>"
                        + "\n".join(_item_to_html(it, i, settings, with_answer=True)
                                    for i, it in enumerate(items, 1)))

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body, {{delimiters: [
    {{left: '$$', right: '$$', display: true}},
    {{left: '$', right: '$', display: false}}]}});"></script>
<style>
@page {{ size: {paper}; margin: 18mm; }}
body {{ font-family: "Source Han Serif SC", "SimSun", serif; font-size: {font_px};
       max-width: 180mm; margin: 0 auto; line-height: 1.8; }}
h1 {{ text-align: center; font-size: 1.5em; }}
.name-line {{ text-align: center; margin: 12px 0 24px; font-size: 1.05em; }}
.question {{ margin-bottom: 8px; }}
.qnum {{ font-weight: bold; margin-bottom: 4px; }}
.blank {{ border-bottom: none; }}
.page-break {{ page-break-before: always; }}
.toolbar {{ position: fixed; top: 12px; right: 16px; }}
.toolbar button {{ font-size: 14px; padding: 8px 16px; cursor: pointer; }}
@media print {{ .toolbar {{ display: none; }} }}
.offline-note {{ color: #b00; display: none; }}
</style>
</head>
<body>
<div class="toolbar"><button onclick="window.print()">🖨️ 打印</button></div>
<h1>{title}{date_line}</h1>
{name_line}
<script>if (!window.katex) {{ document.addEventListener('DOMContentLoaded', function() {{
  document.querySelectorAll('.offline-note').forEach(function(e){{ e.style.display='block'; }}); }}); }}</script>
<p class="offline-note">⚠️ 数学公式渲染需要联网加载 KaTeX。当前未联网，公式显示为源码；建议联网后刷新，或使用应用的 PDF 导出。</p>
{questions_html}
{answers_html}
</body>
</html>"""
