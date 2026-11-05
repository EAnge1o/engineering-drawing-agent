"""测试集评估脚本（65 例）。

类别：正常(20) / 孔位越界(15) / 边距级联(10) / 间距冲突(5) / 边界可修(5) /
      低置信拒绝(5) / 边界负样本(5)

运行：在 backend 目录下执行 `python scripts/evaluate_suite.py`
输出：outputs/metrics.json 与终端汇总表。
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

from app.demo import build_plate_spec  # noqa: E402
from app.evaluate import Case, aggregate, compute_impact, evaluate_case  # noqa: E402
from app.propagate import set_param  # noqa: E402
from app.state import run_repair_loop  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs")


def _base(length: float):
    spec = build_plate_spec(False)
    set_param(spec, "plate.L", length)
    return spec


def build_cases() -> list[Case]:
    cases: list[Case] = []
    lengths = [110 + 10 * i for i in range(20)]  # 110..300

    # 1) 正常图（负样本）：无问题，不应被修改
    for i, L in enumerate(lengths):
        cases.append(Case(f"clean_{i}", _base(L), budget=5, negative=True))

    # 2) 孔位越界：右上孔 x 与推断边距冲突（可自动修复，期望仲裁回 L-margin）
    for i in range(15):
        L = 110 + 10 * i
        base = _base(L)
        spec = base.clone()
        set_param(spec, "hole.x4", L - 5.0)
        cases.append(Case(f"hole_offset_{i}", spec, budget=5,
                          truth_issues={"c_h4_inside"},
                          expect_values={"hole.x4": L - 15.0},
                          impact_base=base, change=("hole.x4", L - 5.0)))

    # 3) 边距级联：一次改参数触发 4 条孔位约束失败
    for i in range(10):
        base = _base(120 + 10 * i)
        spec = base.clone()
        set_param(spec, "margin", 5.0)
        cases.append(Case(f"margin_cascade_{i}", spec, budget=10,
                          truth_issues={f"c_h{k}_inside" for k in range(1, 5)},
                          impact_base=base, change=("margin", 5.0)))

    # 4) 间距冲突：无法安全自动修复 -> 期望拒绝
    for i in range(5):
        spec = _base(120 + 10 * i)
        set_param(spec, "hole.x3", 20.0)
        set_param(spec, "hole.y3", 20.0)
        cases.append(Case(f"spacing_conflict_{i}", spec, budget=5,
                          truth_issues={"c_sp_h1h3"}, expect_refuse=True))

    # 5) 边界可修：圆角超上限，应修复到上限
    for i in range(5):
        spec = _base(120 + 10 * i)
        set_param(spec, "fillet.r", 10.2)
        cases.append(Case(f"fillet_over_{i}", spec, budget=5,
                          truth_issues={"c_fillet_max"},
                          expect_values={"fillet.r": 10.0}))

    # 6) 低置信拒绝：缺陷存在但证据置信度低于阈值
    for i in range(5):
        L = 120 + 10 * i
        spec = _base(L)
        set_param(spec, "hole.x4", L - 5.0)
        spec.params["hole.x4"].evidence[0].confidence = 0.40
        cases.append(Case(f"low_conf_refuse_{i}", spec, budget=5,
                          truth_issues={"c_h4_inside"}, expect_refuse=True))

    # 7) 边界负样本：圆角恰在上限（应通过且不被误修）
    for i in range(5):
        spec = _base(120 + 10 * i)
        set_param(spec, "fillet.r", 10.0)
        cases.append(Case(f"fillet_boundary_{i}", spec, budget=5, negative=True))

    return cases


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    cases = build_cases()
    rows: list[dict] = []
    details: list[dict] = []

    for case in cases:
        impact = None
        if case.change:
            baseline = case.impact_base or case.spec
            impact = compute_impact(baseline, case.change[0], case.change[1])
        result = run_repair_loop(case.spec, budget=case.budget, task_id=case.name)
        metrics = evaluate_case(case, result, impact)
        rows.append(metrics)
        details.append({
            "name": case.name,
            "state": result["state"],
            "remaining": result["remaining"],
            "fixes": result["fixes"],
            "metrics": metrics,
            "impact": impact,
        })
        print(f"  {case.name:22s} state={result['state']:8s} "
              f"det={metrics['detection_rate']:.2f} repair={metrics['repair_success_rate']:.2f} "
              f"used={metrics['budget_used']}/{case.budget}")

    summary = aggregate(rows)
    print(f"\n== 汇总指标（{len(cases)} 例） ==")
    for key, val in summary.items():
        print(f"  {key:26s}: {val}")

    out = os.path.join(OUT, "metrics.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "details": details}, fh, ensure_ascii=False, indent=2)
    print(f"\n指标已保存: {out}")


if __name__ == "__main__":
    main()