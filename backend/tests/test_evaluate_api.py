"""指标评估与 API 路由测试。"""
from app.api import app
from app.demo import build_plate_spec, plate_blueprint
from app.evaluate import aggregate, evaluate_run
from app.parse import parse_blueprint
from app.state import run_repair_loop


def test_evaluate_run_detects_and_repairs():
    spec = build_plate_spec(with_defect=True)
    result = run_repair_loop(spec, budget=5)
    metrics = evaluate_run(result, truth_issue_ids={"c_h4_inside"})
    assert metrics["detection_rate"] == 1.0
    assert metrics["repair_success_rate"] == 1.0
    assert metrics["budget_ok"] is True


def test_evaluate_aggregate():
    spec = build_plate_spec(with_defect=True)
    r1 = run_repair_loop(spec.clone(), budget=5)
    r2 = run_repair_loop(build_plate_spec(with_defect=True), budget=5)
    agg = aggregate([evaluate_run(r1, {"c_h4_inside"}), evaluate_run(r2, {"c_h4_inside"})])
    assert agg["n_runs"] == 2
    assert agg["budget_compliance_rate"] == 1.0


def test_api_routes_registered():
    paths = {r.path for r in app.routes}
    for expected in [
        "/api/health",
        "/api/tasks",
        "/api/tasks/{tid}",
        "/api/tasks/{tid}/issues",
        "/api/tasks/{tid}/model",
        "/api/tasks/{tid}/fix",
        "/api/tasks/{tid}/report",
        "/api/tasks/{tid}/export",
    ]:
        assert expected in paths, f"缺少路由 {expected}"


def test_api_create_task_core_flow():
    """直接调用处理函数，验证核心流程（避免依赖 httpx TestClient）。"""
    from app.api import CreateTaskReq, FixReq, create_task, fix_task, get_issues

    resp = create_task(CreateTaskReq(with_defect=True, task_id="T-TEST"))
    assert resp["task_id"] == "T-TEST"
    assert any(i["constraint_id"] == "c_h4_inside" for i in resp["issues"])

    issues = get_issues("T-TEST")
    assert issues["issues"]

    result = fix_task("T-TEST", FixReq(budget=5, mode="A1"))
    assert result["state"] == "DONE"
    assert result["remaining"] == []


def test_parse_and_audit_consistency():
    res = parse_blueprint(plate_blueprint(with_defect=False))
    assert res.pending == []
    assert res.spec.constraints