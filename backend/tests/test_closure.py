"""闭环测试：审查 → 修复 → 回归验证 → 回滚/拒绝 → 持久化。"""
from app.audit import audit
from app.demo import build_plate_spec
from app.propagate import set_param
from app.rules import check_all
from app.state import run_repair_loop
from app.store import list_tasks, load_task, save_task


def test_repair_closes_single_defect():
    spec = build_plate_spec(with_defect=True)
    result = run_repair_loop(spec, budget=5)

    assert result["state"] == "DONE"
    assert result["resolved"] >= 1
    assert result["remaining"] == []
    assert check_all(spec) == []

    first = result["fixes"][0]
    assert first["rolled_back"] is False
    assert first["regression_passed"] is True
    # 修复目标为右上孔 x4 -> 105（L - margin）
    assert any(ch["param"] == "hole.x4" and ch["new"] == 105.0 for ch in first["changes"])
    # 影响集非空（体现依赖图分析）
    assert first["affected_constraints"]


def test_budget_is_hard_limit():
    spec = build_plate_spec(with_defect=True)
    result = run_repair_loop(spec, budget=1)
    assert result["budget"]["used"] <= 1


def test_low_confidence_refuses_auto_fix():
    spec = build_plate_spec(with_defect=True)
    spec.params["hole.x4"].evidence[0].confidence = 0.40
    result = run_repair_loop(spec, budget=5, auto_threshold=0.55)
    assert result["budget"]["used"] == 0
    assert any(p["reason"] == "low_confidence" for p in result["pending_confirmation"])


def test_cascade_repair_from_margin():
    spec = build_plate_spec(with_defect=False)
    set_param(spec, "margin", 5.0)
    assert len(check_all(spec)) == 4

    result = run_repair_loop(spec, budget=10)
    assert check_all(spec) == []
    assert result["remaining"] == []


def test_persistence_roundtrip(tmp_path):
    db = str(tmp_path / "test_agent.db")
    spec = build_plate_spec(with_defect=True)
    result = run_repair_loop(spec, budget=5)
    save_task("T-001", result, spec=spec, state=result["state"], db=db)

    loaded = load_task("T-001", db=db)
    assert loaded is not None
    assert loaded["state"] == "DONE"
    assert "spec" in loaded

    tasks = list_tasks(db=db)
    assert any(t["task_id"] == "T-001" for t in tasks)