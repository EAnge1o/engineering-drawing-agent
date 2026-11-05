"""LLM 适配层与证据链测试。"""
import os
from uuid import uuid4

from app.api import (
    CreateTaskReq,
    FixReq,
    _create_task_from_drawing_file,
    compare_task,
    create_task,
    fix_task,
)
from app.evidence import build_evidence, verify_evidence
from app.llm import explain_run, llm_available


def _tid() -> str:
    return f"T-{uuid4().hex[:8]}"


def test_llm_unavailable_degrades_to_deterministic(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert llm_available() is False
    result = {
        "issues": [{"constraint_id": "c_h4_inside"}],
        "fixes": [{"fix_id": "fix1", "changes": [{"param": "hole.x4", "old": 115.0, "new": 105.0}]}],
        "state": "DONE",
        "remaining": [],
        "pending_confirmation": [],
    }
    out = explain_run(result)
    assert out["source"] == "deterministic"
    assert "hole.x4" in out["changes"]
    assert out["pending_confirmation"] == []


def test_evidence_pack_is_verifiable(tmp_path):
    result = {"state": "DONE", "budget": {"used": 1, "total": 5}, "issues": [], "fixes": []}
    manifest = build_evidence("T-EV", result, outdir=str(tmp_path), spec_snapshot={"a": 1})
    assert os.path.exists(manifest["manifest_path"])
    assert manifest["files"], "证据清单应至少含报告文件"

    verification = verify_evidence(manifest["manifest_path"])
    assert verification["all_ok"] is True

    # 篡改后应校验失败
    report_path = os.path.join(manifest["dir"], "report.json")
    with open(report_path, "a", encoding="utf-8") as fh:
        fh.write("\n// tampered\n")
    assert verify_evidence(manifest["manifest_path"])["all_ok"] is False


def test_compare_endpoint_reports_diff():
    tid = _tid()
    resp = create_task(CreateTaskReq(with_defect=True, task_id=tid))
    assert resp["task_id"] == tid
    fix_task(tid, FixReq(budget=5, mode="A1"))

    cmp = compare_task(tid)
    assert cmp["before_issue_count"] >= 1
    assert cmp["after_issue_count"] == 0
    assert any(c["param"] == "hole.x4" for c in cmp["changed_params"])
    assert "c_h4_inside" in cmp["resolved"]


def test_drawing_task_compare():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pdf = os.path.join(root, "samples", "plate_defect.pdf")
    if not os.path.exists(pdf):
        import pytest

        pytest.skip("缺少样例 PDF")
    tid = _tid()
    _create_task_from_drawing_file(pdf, task_id=tid)
    fix_task(tid, FixReq(budget=5, mode="A1"))
    cmp = compare_task(tid)
    assert cmp["after_issue_count"] == 0
    assert cmp["resolved"]