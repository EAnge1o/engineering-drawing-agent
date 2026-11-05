"""图纸上传端点测试（直接调用处理函数，避免依赖回环 socket）。"""
import os

import pytest

from app.api import _create_task_from_drawing_file
from app.audit import audit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLES = os.path.join(ROOT, "samples")


def _sample(name: str) -> str:
    p = os.path.join(SAMPLES, name)
    if not os.path.exists(p):
        pytest.skip(f"缺少样例 {p}")
    return p


def test_create_task_from_normal_drawing():
    resp = _create_task_from_drawing_file(_sample("plate_normal.pdf"), task_id="T-DWG1")
    assert resp["task_id"] == "T-DWG1"
    assert resp["source_file"] == "plate_normal.pdf"
    assert resp["parse"]["drawing"] is not None
    assert resp["issues"] == []


def test_create_task_from_defect_drawing_detects_issue():
    resp = _create_task_from_drawing_file(_sample("plate_defect.pdf"), task_id="T-DWG2")
    codes = {i["constraint_id"] for i in resp["issues"]}
    assert any(c and c.startswith("c_h") and c.endswith("_inside") for c in codes), codes