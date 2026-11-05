"""核心逻辑测试：数据模型 / 依赖图 / 规则引擎。"""
from app.demo import build_plate_spec
from app.graph import (
    affected_constraints,
    affected_features,
    build_graph,
    impact_metrics,
)
from app.propagate import set_param
from app.rules import check_all, summarize


def test_clean_spec_has_no_issues():
    spec = build_plate_spec(with_defect=False)
    issues = check_all(spec)
    assert issues == [], f"干净图纸不应有问题，却得到 {[i.constraint_id for i in issues]}"


def test_single_hole_offset_detected():
    spec = build_plate_spec(with_defect=True)
    issues = check_all(spec)
    codes = {i.constraint_id for i in issues}
    # 右上孔 x 标注为 115（越界）：仅该孔触发 inside 约束
    assert codes == {"c_h4_inside"}, codes
    summary = summarize(issues)
    assert summary["total"] == 1 and summary["geometric"] == 1


def test_margin_change_causes_cascade():
    """改一个参数（边距）→ 级联破坏 4 条孔位约束。"""
    spec = build_plate_spec(with_defect=False)
    set_param(spec, "margin", 5.0)
    issues = check_all(spec)
    codes = {i.constraint_id for i in issues}
    assert codes == {f"c_h{i}_inside" for i in range(1, 5)}, codes


def test_impact_analysis_of_changing_L():
    spec = build_plate_spec(with_defect=False)
    g = build_graph(spec)

    cons = affected_constraints(g, ["plate.L"])
    feats = affected_features(g, ["plate.L"])

    # plate.L -> x2, x4 且所有 inside 约束直接引用 L -> 均需回归
    assert {"c_h1_inside", "c_h2_inside", "c_h3_inside", "c_h4_inside",
            "c_sp_h1h2", "c_sp_h2h4"} <= cons
    # 与 L 无关的约束不应出现
    assert "c_diam_eq" not in cons
    assert "c_fillet_max" not in cons
    assert "c_T_pos" not in cons
    # 下游特征
    assert {"plate_body", "hole_h1", "hole_h4", "hole_pattern", "fillet_01"} <= feats


def test_impact_metrics():
    m = impact_metrics({"a", "b"}, {"a", "b", "c"})
    assert m["precision"] == 1.0
    assert m["recall"] < 1.0
    assert m["fp"] == 0
    assert m["fn"] == 1

    exact = impact_metrics({"a", "b"}, {"a", "b"})
    assert exact["f1"] == 1.0


def test_evidence_status_resolution():
    spec = build_plate_spec(with_defect=True)
    x4 = spec.params["hole.x4"]
    # 缺陷孔位为观测值且置信度 0.6
    assert x4.status.value == "observed"
    assert 0.5 <= x4.confidence <= 0.7

def test_derived_propagation():
    spec = build_plate_spec(with_defect=False)
    set_param(spec, "plate.L", 130.0)
    # x2/x4 = L - margin 应自动重算
    assert spec.value("hole.x2") == 115.0
    assert spec.value("hole.x4") == 115.0
    assert spec.value("hole.x1") == 15.0
    assert check_all(spec) == []