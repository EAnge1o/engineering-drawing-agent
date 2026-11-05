"""解析层与几何适配层测试。"""
from app.audit import audit
from app.cad import cadquery_available, export_step_stl, geometry_summary
from app.demo import plate_blueprint
from app.models import AutoMode
from app.parse import THRESH_HIGH, THRESH_LOW, decide_mode, parse_blueprint


def test_decide_mode_boundaries():
    assert decide_mode(0.99) == AutoMode.A0
    assert decide_mode(THRESH_HIGH) == AutoMode.A0
    assert decide_mode(0.60) == AutoMode.A1
    assert decide_mode(THRESH_LOW) == AutoMode.A1
    assert decide_mode(0.30) == AutoMode.A2
    assert decide_mode(0.99, preference="manual") == AutoMode.A2


def test_parse_clean_blueprint():
    res = parse_blueprint(plate_blueprint(with_defect=False))
    # fillet.r 置信度 0.8 -> A1（需确认），整体为 A1
    assert res.overall_mode == AutoMode.A1
    assert res.pending == []
    assert "plate.L" in res.spec.params
    assert res.spec.value("hole.x2") == 105.0
    # 干净蓝图不应有问题
    assert audit(res.spec) == []


def test_parse_defect_blueprint_detects_issue():
    res = parse_blueprint(plate_blueprint(with_defect=True))
    assert res.spec.value("hole.x4") == 115.0
    # 观测值覆盖推断值后，派生关系应断开
    assert res.spec.params["hole.x4"].kind == "geometry"
    assert res.spec.params["hole.x4"].expr is None
    issues = audit(res.spec)
    assert any(i.constraint_id == "c_h4_inside" for i in issues)


def test_geometry_summary_is_deterministic():
    res = parse_blueprint(plate_blueprint(with_defect=False))
    s = geometry_summary(res.spec)
    assert s["bbox"] == {"length": 120.0, "width": 80.0, "height": 6.0}
    assert s["hole_count"] == 4
    assert s["volume"] > 0
    # 板体积 - 4 孔体积
    assert abs(s["volume"] - (120 * 80 * 6 - 4 * 3.141592653589793 * 3.25 ** 2 * 6)) < 1.0


def test_export_without_kernel_writes_summary(tmp_path):
    res = parse_blueprint(plate_blueprint(with_defect=False))
    paths = export_step_stl(res.spec, str(tmp_path))
    if cadquery_available():
        assert "step" in paths and "stl" in paths
    else:
        assert "json" in paths
        assert (tmp_path / "model_summary.json").exists()