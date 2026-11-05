"""扩展评估指标测试：影响集 P/R、仲裁正确率、拒绝正确率、误修率。"""
from app.demo import build_plate_spec
from app.evaluate import Case, aggregate, compute_impact, evaluate_case
from app.propagate import set_param
from app.state import run_repair_loop


def test_impact_covers_all_newly_failed_constraints():
    """影响集（依赖图可达）必须覆盖变更后实际新增失败的全部约束（recall=1）。"""
    spec = build_plate_spec(with_defect=False)
    # 把边距改小会真实触发 4 条孔位约束失败
    impact = compute_impact(spec, "margin", 5.0)
    assert impact["truth"], "该变更应真实触发约束失败"
    assert impact["recall"] == 1.0, impact
    assert {"c_h1_inside", "c_h4_inside"} <= set(impact["truth"])
    assert {"c_h1_inside", "c_h4_inside"} <= set(impact["predicted"])


def test_impact_no_failure_case_still_recall_one():
    """变更后无约束失效时，recall 应为 1（无误漏），仅 precision 受预测集大小影响。"""
    spec = build_plate_spec(with_defect=False)
    impact = compute_impact(spec, "plate.L", 130.0)  # 放大尺寸，约束仍满足
    assert impact["truth"] == []
    assert impact["recall"] == 1.0


def test_arbitration_accuracy_on_hole_offset():
    spec = build_plate_spec(with_defect=False)
    set_param(spec, "plate.L", 120.0)
    set_param(spec, "hole.x4", 115.0)  # 与边距 15 冲突
    case = Case("offset", spec, budget=5, truth_issues={"c_h4_inside"},
                expect_values={"hole.x4": 105.0})
    result = run_repair_loop(spec, budget=5)
    metrics = evaluate_case(case, result)
    assert metrics["arbitration_accuracy"] == 1.0
    assert metrics["repair_success_rate"] == 1.0


def test_refusal_accuracy_on_low_confidence():
    spec = build_plate_spec(with_defect=True)
    spec.params["hole.x4"].evidence[0].confidence = 0.40
    case = Case("lowconf", spec, budget=5, truth_issues={"c_h4_inside"}, expect_refuse=True)
    result = run_repair_loop(spec, budget=5, auto_threshold=0.55)
    metrics = evaluate_case(case, result)
    assert metrics["refusal_correct"] == 1.0
    assert metrics["fixes_attempted"] == 0


def test_misrepair_rate_zero_on_negative_sample():
    spec = build_plate_spec(with_defect=False)
    case = Case("clean", spec, budget=5, negative=True)
    result = run_repair_loop(spec, budget=5)
    metrics = evaluate_case(case, result)
    assert metrics["negative_modified"] == 0.0


def test_aggregate_includes_differentiating_metrics():
    spec = build_plate_spec(with_defect=True)
    case = Case("d", spec, budget=5, truth_issues={"c_h4_inside"},
                expect_values={"hole.x4": 105.0})
    result = run_repair_loop(spec, budget=5)
    row = evaluate_case(case, result, compute_impact(build_plate_spec(False), "plate.L", 130.0))
    agg = aggregate([row])
    assert agg["n_runs"] == 1
    assert "impact_recall" in agg and "arbitration_accuracy" in agg
    assert "misrepair_rate" in agg and "refusal_accuracy" in agg