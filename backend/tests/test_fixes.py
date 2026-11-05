"""针对 2026-10-31 审查问题的修复回归测试。

每条对应一个原始问题编号，防止回归。
"""
import asyncio
import os
import tempfile
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api import (
    CreateTaskReq,
    FixReq,
    _create_task_from_drawing_file,
    compare_task,
    create_task,
    create_task_from_drawing,
    fix_task,
    restore_tasks,
)
from app.audit import audit
from app.cad import export_step_stl, geometry_summary
from app.demo import build_plate_spec, plate_blueprint
from app.evidence import build_evidence, verify_evidence
from app.models import AutoMode, Param, Spec
from app.parse import parse_blueprint
from app.propagate import _eval_expr, set_param
from app.state import run_repair_loop
from app.store import list_tasks, load_task, save_task


# --------------------------------------------------------------------- H-1
def test_evidence_pack_is_self_verifiable(tmp_path):
    spec = build_plate_spec(with_defect=True)
    result = run_repair_loop(spec, budget=5)
    out = tmp_path / "out"
    extra = [p for p in export_step_stl(spec, str(out)).values() if os.path.isfile(p)]
    manifest = build_evidence("T-EV", result, outdir=str(tmp_path / "ev"),
                              extra_files=extra, spec_snapshot=spec.to_dict())
    v = verify_evidence(manifest["manifest_path"])
    assert v["all_ok"] is True, v
    assert all(c["ok"] for c in v["checks"])
    # 产物已被复制进证据目录
    for item in manifest["files"]:
        assert os.path.exists(os.path.join(manifest["dir"], item["path"]))


# --------------------------------------------------------------------- H-2
@pytest.mark.parametrize("n_holes", [2, 3, 4, 5])
def test_geometry_summary_handles_any_hole_count(n_holes):
    spec = build_plate_spec(with_defect=False)
    for i in range(1, 6):
        if i > n_holes:
            spec.params.pop(f"hole.x{i}", None)
            spec.params.pop(f"hole.y{i}", None)
        elif f"hole.x{i}" not in spec.params:
            spec.add_param(Param(f"hole.x{i}", 60.0, evidence=[]))
            spec.add_param(Param(f"hole.y{i}", 40.0, evidence=[]))
    s = geometry_summary(spec)
    assert s["hole_count"] == n_holes
    assert len(s["holes"]) == n_holes
    assert s["volume"] > 0


def test_export_with_fewer_holes(tmp_path):
    spec = build_plate_spec(with_defect=False)
    for i in (3, 4):
        spec.params.pop(f"hole.x{i}", None)
        spec.params.pop(f"hole.y{i}", None)
    paths = export_step_stl(spec, str(tmp_path))
    assert paths  # 不再抛 KeyError


# --------------------------------------------------------------------- H-4
def test_invalid_mode_is_rejected_by_schema():
    with pytest.raises(ValidationError):
        FixReq(mode="b2")


def test_invalid_budget_is_rejected_by_schema():
    with pytest.raises(ValidationError):
        CreateTaskReq(budget=0)
    with pytest.raises(ValidationError):
        CreateTaskReq(budget=99)
    with pytest.raises(ValidationError):
        CreateTaskReq(preference="weird")


def test_upload_rejects_unsupported_extension():
    class FakeUpload:
        filename = "note.txt"

        async def read(self):
            return b"hello"

    with pytest.raises(Exception) as ei:
        asyncio.run(create_task_from_drawing(FakeUpload()))
    assert "422" in str(ei.value) or "Unsupported" in str(ei.value) or "不支持" in str(ei.value)


# --------------------------------------------------------------------- M-B3
def test_override_purges_duplicates_and_recomputes():
    bp = plate_blueprint(with_defect=False)
    bp["params"].append({"id": "hole.x4", "value": 108.0, "confidence": 0.3,
                         "status": "observed", "source": "dup"})
    bp["overrides"] = [{"id": "hole.x4", "value": 115.0, "confidence": 0.9,
                        "status": "user-confirmed", "source": "ov"}]
    res = parse_blueprint(bp)
    ids = [f.id for f in res.fields]
    assert ids.count("hole.x4") == 1, ids
    # status 透传到 ParsedField
    assert next(f.status.value for f in res.fields if f.id == "hole.x4") == "user-confirmed"

    # override 改动上游参数后，派生参数必须重算
    bp2 = plate_blueprint(with_defect=False)
    bp2["overrides"] = [{"id": "plate.L", "value": 90.0, "confidence": 0.9, "status": "observed"}]
    res2 = parse_blueprint(bp2)
    assert res2.spec.value("hole.x2") == 90.0 - 15.0


# --------------------------------------------------------------------- M-B4
def test_apply_fix_is_transactional():
    spec = build_plate_spec(with_defect=True)
    spec.add_param(Param("bad.derived", 1.0, kind="derived", depends_on=["margin"],
                         expr="plate.L - margin", evidence=[]))
    before = {k: p.value for k, p in spec.params.items()}
    # run_repair_loop 不得抛出，且 spec 不得被半污染
    result = run_repair_loop(spec, budget=5)
    assert result["state"] in {"DONE", "STOPPED"}
    assert any((f.get("note") or "").startswith(("apply 失败", "未预期异常", "回滚")) for f in result["fixes"]) \
        or result["remaining"] == []
    assert spec.value("bad.derived") == before["bad.derived"]


# --------------------------------------------------------------------- M-B2
def test_regression_baseline_refreshes_each_round():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "app", "state.py"), encoding="utf-8").read()
    assert "baseline_now" in src
    assert "baseline_ids = {" not in src


# --------------------------------------------------------------------- M-B7
def test_budget_ok_reflects_exhaustion():
    from app.evaluate import aggregate, evaluate_run

    spec = build_plate_spec(with_defect=False)
    set_param(spec, "margin", 5.0)      # 4 条约束失败，预算 1 必然耗尽
    res = run_repair_loop(spec, budget=1)
    m = evaluate_run(res, {f"c_h{k}_inside" for k in range(1, 5)})
    assert m["budget_ok"] is False
    assert m["budget_exhausted"] is True

    # 零尝试用例在聚合时被跳过
    spec2 = build_plate_spec(with_defect=True)
    spec2.params["hole.x4"].evidence[0].confidence = 0.30
    res2 = run_repair_loop(spec2, budget=5)
    agg = aggregate([evaluate_run(res2, {"c_h4_inside"})])
    assert agg["skipped_no_attempt"] == 1
    assert agg["repair_success_rate"] is None


# --------------------------------------------------------------------- M-B9/M-B10
def test_duplicate_task_id_is_rejected():
    tid = f"T-{uuid4().hex[:8]}"
    create_task(CreateTaskReq(with_defect=True, task_id=tid))
    with pytest.raises(Exception) as ei:
        create_task(CreateTaskReq(with_defect=False, task_id=tid))
    assert "409" in str(ei.value) or "已存在" in str(ei.value)


# --------------------------------------------------------------------- M-B1
def test_persistence_restore_roundtrip(tmp_path):
    db = str(tmp_path / "restore.db")
    spec = build_plate_spec(with_defect=True)
    result = run_repair_loop(spec, budget=5)
    save_task("T-RS", result, spec=spec, state=result["state"], db=db)

    payload = load_task("T-RS", db=db)
    assert payload and "spec" in payload
    rebuilt = Spec.from_dict(payload["spec"])
    assert rebuilt.value("plate.L") == spec.value("plate.L")
    assert set(rebuilt.constraints) == set(spec.constraints)
    assert any(t["task_id"] == "T-RS" for t in list_tasks(db=db))


def test_restore_tasks_fills_memory():
    tid = f"T-{uuid4().hex[:8]}"
    create_task(CreateTaskReq(with_defect=True, task_id=tid))
    fix_task(tid, FixReq(budget=5, mode=AutoMode.A1))
    from app import api as api_mod

    # 清空内存模拟重启，再从磁盘回灌
    api_mod._TASKS.clear()
    restored = restore_tasks()
    assert restored >= 1
    assert tid in api_mod._TASKS
    assert api_mod._TASKS[tid]["spec"].value("plate.L") == 120.0


# --------------------------------------------------------------------- M-B5/M-B6/L-B1
def test_portrait_drawing_scale():
    from app.drawing import CircleItem, DrawingData, RectItem, TextItem, infer_blueprint

    dd = DrawingData(source="p.pdf", text_backend="pdf")
    dd.rects = [RectItem(0, 0, 100, 200)]
    dd.texts = [TextItem("200", 0, 0, 0, 0, 0.9), TextItem("100", 0, 0, 0, 0, 0.9),
                TextItem("4x D10", 0, 0, 0, 0, 0.9)]
    dd.circles = [CircleItem(50, 150, 3)]
    bp = infer_blueprint(dd)
    holes = dict((p["id"], p["value"]) for p in bp["params"] if p["id"].startswith("hole."))
    assert dd.scale_px_per_mm == pytest.approx(1.0)
    assert holes.get("hole.x1") == pytest.approx(50.0, abs=1.0)


def test_hole_inside_accounts_for_radius():
    """孔心恰在板边（边距 0）时应判负：孔不完整在板内。"""
    spec = Spec()
    spec.add_param(Param("plate.L", 100.0))
    spec.add_param(Param("plate.W", 60.0))
    spec.add_param(Param("hole.d", 8.0))
    spec.add_param(Param("hole.x1", 3.0))   # 左侧边距 3 < 半径 4 -> 孔不完整
    spec.add_param(Param("hole.y1", 30.0))
    from app.models import Constraint

    spec.add_constraint(Constraint("c", "hole_inside",
                                   params=["hole.x1", "hole.y1", "plate.L", "plate.W"], target=0.0))
    issues = audit(spec)
    assert any(i.code == "hole_inside" for i in issues), "边距=半径时应判为不合法"


def test_expression_supports_scientific_and_functions():
    assert _eval_expr("1e5", {}) == 100000.0
    assert _eval_expr("max(3,5)", {}) == 5.0
    assert _eval_expr("abs(-3)+1.5", {}) == 4.5
    assert _eval_expr("plate.L - margin", {"plate.L": 120.0, "margin": 15.0}) == 105.0