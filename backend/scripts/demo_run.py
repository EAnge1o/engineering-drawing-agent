"""演示脚本：解析 → 审查 → 影响分析 → 修复 → 报告。

用途：录制功能演示视频、生成码道开发留痕（运行日志与报告）。
运行：在本目录（backend）下执行 `python scripts/demo_run.py`
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

from app.audit import audit  # noqa: E402
from app.cad import export_step_stl, geometry_summary  # noqa: E402
from app.demo import plate_blueprint  # noqa: E402
from app.graph import affected_constraints, build_graph  # noqa: E402
from app.parse import parse_blueprint  # noqa: E402
from app.state import run_repair_loop  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs")


def main() -> None:
    os.makedirs(OUT, exist_ok=True)

    print("== 0. 从真实图纸解析（矢量 PDF） ==")
    pdf = os.path.join(os.path.dirname(os.path.dirname(OUT)), "samples", "plate_defect.pdf")
    if os.path.exists(pdf):
        from app.drawing import parse_drawing
        dr = parse_drawing(pdf)
        dv = dr.drawing or {}
        print(f"  文本后端={dv.get('text_backend')} 比例={dv.get('scale_px_per_mm')} px/mm")
        print(f"  识别尺寸: L={dr.spec.value('plate.L')} W={dr.spec.value('plate.W')} "
              f"d={dr.spec.value('hole.d')} 孔数={len([k for k in dr.spec.params if k.startswith('hole.x')])}")
        for n in dr.notes:
            print(f"  备注: {n}")
    else:
        print("  (跳过：未找到 samples/plate_defect.pdf，可先运行 export_samples.py)")

    print("\n== 1. 解析图纸（自适应工作模式） ==")
    pr = parse_blueprint(plate_blueprint(with_defect=True))
    print(f"整体模式: {pr.overall_mode.value} | 待确认: {pr.pending}")
    for f in pr.fields:
        flag = "需确认" if f.needs_confirm else "自动"
        print(f"  {f.id:12s} = {f.value:<8} conf={f.confidence:.2f} mode={f.mode.value} {flag}")

    print("\n== 2. 三层审查（确定性规则） ==")
    issues = audit(pr.spec)
    for i in issues:
        print(f"  [{i.severity.value}] {i.constraint_id}: {i.evidence[0]}")

    print("\n== 3. 变更影响分析（参数依赖图） ==")
    g = build_graph(pr.spec)
    print(f"  变更 hole.x4 -> 受影响约束: {sorted(affected_constraints(g, ['hole.x4']))}")

    print("\n== 4. 局部修复 + 回归验证（预算=5） ==")
    result = run_repair_loop(pr.spec, budget=5, task_id="DEMO-001")
    for fx in result["fixes"]:
        changes = [(c["param"], c["old"], c["new"]) for c in fx["changes"]]
        print(f"  {fx['fix_id']} 改动={changes}")
        print(f"      回归通过={fx['regression_passed']} 回滚={fx['rolled_back']} 影响={fx['affected_constraints']}")
    print(f"  最终状态: {result['state']} | 剩余问题: {result['remaining']}")

    print("\n== 5. 几何摘要与导出 ==")
    summary = geometry_summary(pr.spec)
    print(f"  包围盒={summary['bbox']} 体积={summary['volume']:.2f} 孔数={summary['hole_count']}")
    paths = export_step_stl(pr.spec, OUT)
    print(f"  导出: {paths}")

    report = {
        "task_id": "DEMO-001",
        "parse": pr.to_dict(),
        "issues": [
            {
                "id": i.id, "constraint_id": i.constraint_id, "code": i.code,
                "layer": i.layer.value, "severity": i.severity.value,
                "confidence": i.confidence, "evidence": i.evidence, "fixable": i.fixable,
                "location": i.location, "fix_hint": i.fix_hint,
            }
            for i in issues
        ],
        "result": result,
        "model": summary,
        "exports": paths,
    }
    out = os.path.join(OUT, "report.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, default=str)
    print(f"\n报告已保存: {out}")


if __name__ == "__main__":
    main()