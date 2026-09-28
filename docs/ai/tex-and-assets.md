# TeX、选择题与图片资源规范

## 1. 题目结构

每道完整题目使用：

```tex
\begin{problem}{年份}{类别}{试卷名称}{题号}{板块}
题干
\end{problem}
\begin{answer}
答案
\end{answer}
\begin{solutions}
解析
\end{solutions}
```

AI 只识别图片中实际存在的答案和解析；原图没有答案或解析时保持为空，不自行解题补写。

## 2. 数学排版红线

- 行内公式使用 `$...$`，行间公式使用独立成行的 `$$...$$`；不要使用 `\(...\)` 或 `\[...\]`。
- 分式、求和、累乘等按 `ocr_prompt.txt` 的规则使用 `\displaystyle`。
- 选择题使用 `choices` 环境和双层花括号：`\choice{{$2$}}`。
- 选择题选项不要手写 `A.`、`B.` 前缀；选项内容保持纯内部 TeX。
- 题目小问直接写 `(1)`、`(2)`，不要为了小问引入 `enumerate`。
- 修改后必须检查花括号、problem 环境、choices 数量和预览结果。

完整 OCR 排版规则以根目录 `ocr_prompt.txt` 为准，本文件只保留项目级边界。

## 3. 图片与 TikZ

- 已有 `tikzpicture` 的题目保留 TikZ 源码，不额外复制成 `questionasset`。
- 扫描题图、统计图、PDF 裁剪图等非 TikZ 图片登记为题目资源，并使用稳定别名引用。
- `questionasset` 别名只使用小写英文、数字和下划线，例如 `figure_01`、`solution_figure_01`。
- 图片说明写入资源的 `caption` 字段，不把说明重复拼进引用名。
- 图片要保存来源页、裁剪区域、用途、排序和审核状态；不确定归属时先标记待审核。
- 详细命名规则见 `../planning/question_asset_naming_standard.md`。
