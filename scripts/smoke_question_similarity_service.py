"""Focused smoke tests for the shared GaokaoWeb-style similarity service."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.question_similarity_service import score_question_pair


def main() -> None:
    identical = score_question_pair(
        r"在集合 $A$ 中，若 $x\in A$，求 $x+1=5$。",
        r"在集合 $A$ 中，若 $x\in A$，求 $x+1=5$。",
    )
    assert identical["kind"] == "exact" and identical["score"] == 1.0

    sensitive = score_question_pair(
        r"若集合 $A\cap B$ 非空，求其元素个数。",
        r"若集合 $A\cup B$ 非空，求其元素个数。",
    )
    assert sensitive["kind"] != "exact"

    number_variant = score_question_pair(
        r"已知函数 $f(x)=x^2+4x+4$，求其最小值。",
        r"已知函数 $f(x)=x^2+5x+5$，求其最小值。",
    )
    assert number_variant["kind"] != "exact"
    assert number_variant["score"] is not None
    assert number_variant["numf"] < 1.0

    image_mismatch = score_question_pair(
        r"如图，求三角形 $ABC$ 的面积。",
        r"求三角形 $ABC$ 的面积。\questionasset{triangle.png}",
    )
    assert image_mismatch["kind"] != "exact"

    choice_result = score_question_pair(
        r"函数 $f(x)$ 的定义域为（ ）",
        r"函数 $f(x)$ 的定义域是（ ）",
        left_choices=[r"$x>0$", r"$x\geq 0$", r"$x<0$", r"$x\leq 0$"],
        right_choices=[r"$x>0$", r"$x\geq 0$", r"$x<0$", r"$x\leq 0$"],
        left_question_type_id=1,
        right_question_type_id=1,
    )
    assert choice_result["choice_mode"] in {"stem", "stem+choices"}
    assert choice_result["score"] is not None

    prefix_result = score_question_pair(
        r"设函数 $f(x)=x^2$。（1）求 $f(1)$。（2）求 $f(x)$ 的最小值。",
        r"已知函数 $f(x)=x^2$。（1）求 $f(1)$。（2）求 $f(x)$ 的最小值。（3）求其图象。",
        allow_sub=True,
    )
    assert prefix_result["channel"] == "前缀子题"

    short_result = score_question_pair(r"求 $4+5$。", r"求 $4+4$。")
    assert short_result["score"] is None

    long_result = score_question_pair("求" + "甲" * 12, "求" + "甲" * 120)
    assert long_result["score"] is None

    print("question similarity service smoke test passed")


if __name__ == "__main__":
    main()
