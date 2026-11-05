"""华为云服务接入测试。

覆盖：
- 未配置时全部优雅降级（不改变原有确定性闭环行为）
- 多模态候选值的归一化、融合与状态标记
- OBS 未配置时的快速失败
- 证据包在无云环境下的本地可校验性
- 指标缓冲聚合、异步任务队列
- 新增 API 端点
"""
from __future__ import annotations

import json
import time
from uuid import uuid4

import pytest

from app import cloud, jobs, metrics, obs
from app.api import (
    CreateTaskReq,
    FixReq,
    cloud_status,
    create_task,
    evidence_task,
    export_task,
    fix_task,
    fix_task_async,
    get_job,
    get_meta,
    metrics_summary,
    list_jobs,
)
from app.drawing import DrawingData, infer_blueprint, vision_candidates
from app.evidence import build_evidence, verify_evidence
from app.llm import extract_json


def _tid() -> str:
    return f"T-{uuid4().hex[:8]}"


# --------------------------------------------------------------------------- #
# 配置与探测
# --------------------------------------------------------------------------- #
def test_cloud_status_shape(monkeypatch):
    for k in ("LLM_BASE_URL", "OBS_ENDPOINT", "OBS_BUCKET", "OBS_AK", "OBS_SK",
              "FN_ENDPOINT", "CES_AK", "CES_SK"):
        monkeypatch.delenv(k, raising=False)

    st = cloud.status()
    assert set(st) >= {"maas", "obs", "functiongraph", "ces", "enabled_count"}
    assert st["enabled_count"] == 0
    assert st["maas"]["available"] is False
    assert st["obs"]["available"] is False
    assert st["functiongraph"]["available"] is False


def test_cloud_status_reflects_env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.modelarts-maas.com/openai/v1")
    monkeypatch.setenv("FN_ENDPOINT", "https://example.com/fn")
    st = cloud.status()
    assert st["maas"]["available"] is True
    assert st["maas"]["host"] == "api.modelarts-maas.com"
    assert st["functiongraph"]["available"] is True


def test_mask_does_not_leak(monkeypatch):
    monkeypatch.setenv("OBS_AK", "AKIA1234567890ABCDEF")
    st = cloud.status()
    assert "1234567890ABCDEF" not in st["obs"]["ak_masked"]
    assert st["obs"]["ak_masked"].startswith("AKIA")


# --------------------------------------------------------------------------- #
# 多模态候选值
# --------------------------------------------------------------------------- #
def test_vision_candidates_none_without_config(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert vision_candidates("whatever.png") is None


def test_extract_json_tolerates_fences_and_noise():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('说明文字 {"a": 2} 结尾') == {"a": 2}
    assert extract_json("完全不是 JSON") is None
    assert extract_json(None) is None


def test_normalize_vision_keeps_valid_items():
    from app.drawing import _normalize_vision

    raw = {
        "unit": "mm",
        "plate": {"L": {"value": 120, "confidence": 0.9},
                  "W": {"value": 80, "confidence": 0.9},
                  "T": {"value": None, "confidence": 0}},
        "fillet_r": {"value": 5, "confidence": 0.6},
        "hole": {"d": {"value": 6.5, "confidence": 0.85},
                 "centers": [{"x": 15, "y": 15, "confidence": 0.8},
                             {"x": -1, "y": 10, "confidence": 0.9}]},
        "notes": ["厚度未标注"],
    }
    norm = _normalize_vision(raw)
    assert norm["params"]["plate.L"]["value"] == 120.0
    assert "plate.T" not in norm["params"], "value=null 的项应被丢弃"
    assert norm["params"]["hole.d"]["value"] == 6.5
    # 负坐标是非法孔位，必须被过滤
    assert len(norm["holes"]) == 1
    assert norm["notes"] == ["厚度未标注"]


def test_normalize_vision_drops_garbage():
    from app.drawing import _normalize_vision

    assert _normalize_vision({"plate": "not-a-dict"}) == {}
    assert _normalize_vision({}) == {}


def test_infer_blueprint_uses_vision_without_rects():
    """没有检测到外轮廓时，多模态候选值仍可支撑建模（核心增强）。"""
    dd = DrawingData(source="bitmap.png", text_backend="manual")
    vision = {
        "params": {
            "plate.L": {"value": 120.0, "confidence": 0.9},
            "plate.W": {"value": 80.0, "confidence": 0.88},
            "plate.T": {"value": 6.0, "confidence": 0.6},
            "hole.d": {"value": 6.5, "confidence": 0.85},
        },
        "holes": [
            {"x": 15.0, "y": 15.0, "confidence": 0.8},
            {"x": 105.0, "y": 15.0, "confidence": 0.8},
            {"x": 15.0, "y": 65.0, "confidence": 0.8},
            {"x": 105.0, "y": 65.0, "confidence": 0.8},
        ],
    }
    bp = infer_blueprint(dd, vision=vision)

    by_id = {p["id"]: p for p in bp["params"]}
    assert by_id["plate.L"]["value"] == 120.0
    assert by_id["plate.L"]["source"] == "maas:vision"
    # 模型值必须是 inferred（不能冒充观测值）
    assert by_id["plate.L"]["status"] == "inferred"
    assert by_id["hole.d"]["status"] == "inferred"
    assert by_id["hole.x1"]["value"] == 15.0
    assert by_id["hole.y4"]["value"] == 65.0
    assert bp["vision"]["used"] is True


def test_infer_blueprint_without_rects_and_vision_still_raises():
    """保持原有行为：既无轮廓也无模型候选时必须明确报错。"""
    dd = DrawingData(source="bitmap.png", text_backend="manual")
    with pytest.raises(ValueError, match="未检测到零件外轮廓"):
        infer_blueprint(dd)


def test_infer_blueprint_legacy_path_unaffected():
    """无 vision 时输出结构与接入前一致（source 为图纸/规则）。"""
    from app.drawing import RectItem, TextItem

    dd = DrawingData(source="plate.pdf", text_backend="pdf")
    dd.rects = [RectItem(0, 0, 240, 160)]
    dd.texts = [TextItem("120", 10, 10), TextItem("80", 10, 30), TextItem("φ6.5", 50, 50)]
    bp = infer_blueprint(dd)
    by_id = {p["id"]: p for p in bp["params"]}
    assert by_id["plate.L"]["value"] == 120.0
    assert by_id["plate.L"]["source"] == "drawing:overall"
    assert by_id["plate.L"]["status"] == "observed"
    assert bp["vision"]["used"] is False


def test_parse_drawing_end_to_end_with_mocked_vision(monkeypatch):
    """端到端：mock 模型返回 → parse_drawing 产出带 maas:vision 证据的 Spec。

    证明多模态链路真的接到了解析主流程（而不只是 infer_blueprint 单测）。
    """
    import os

    from app import llm
    from app.drawing import parse_drawing

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pdf = os.path.join(root, "samples", "plate_normal.pdf")
    if not os.path.exists(pdf):
        pytest.skip("缺少样例 PDF")

    monkeypatch.setenv("LLM_BASE_URL", "https://api.modelarts-maas.com/openai/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    fake = json.dumps({
        "plate": {"L": {"value": 120.0, "confidence": 0.9},
                  "W": {"value": 80.0, "confidence": 0.9},
                  "T": {"value": 6.0, "confidence": 0.55}},
        "hole": {"d": {"value": 6.5, "confidence": 0.85},
                 "centers": [{"x": 15, "y": 15, "confidence": 0.8}]},
        "notes": ["mock 模型输出"],
    })
    monkeypatch.setattr(llm, "complete_vision", lambda *a, **k: fake)

    res = parse_drawing(pdf)
    spec = res.spec

    # 模型值进入 Spec，且被标记为 inferred / maas:vision
    ev = spec.params["plate.L"].evidence[0]
    assert ev.source == "maas:vision"
    assert ev.status.value == "inferred"
    assert spec.params["plate.L"].value == 120.0

    # 解析结果里保留模型原文，便于审计
    assert res.drawing["vision"]["params"]["plate.L"]["value"] == 120.0
    # 模型提示进入 notes
    assert any("多模态" in n for n in res.notes)


def test_parse_drawing_skips_vision_when_disabled(monkeypatch):
    """use_vision=False 时必须完全不调用模型（可复现的确定性路径）。"""
    import os

    from app import llm
    from app.drawing import parse_drawing

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pdf = os.path.join(root, "samples", "plate_normal.pdf")
    if not os.path.exists(pdf):
        pytest.skip("缺少样例 PDF")

    monkeypatch.setenv("LLM_BASE_URL", "https://api.modelarts-maas.com/openai/v1")

    called = {"n": 0}

    def _spy(*a, **k):
        called["n"] += 1
        return None

    monkeypatch.setattr(llm, "complete_vision", _spy)

    res = parse_drawing(pdf, use_vision=False)
    assert called["n"] == 0
    assert "vision" not in res.drawing


def test_vision_circuit_breaker_skips_after_failures(monkeypatch):
    """连续失败达阈值后进入冷却期，避免每次解析都阻塞到超时。"""
    from app import drawing as dw
    from app import llm

    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/openai/v1")
    # 重置熔断状态
    monkeypatch.setattr(dw, "_VISION_FAILS", 0)
    monkeypatch.setattr(dw, "_VISION_COOLDOWN_UNTIL", 0.0)

    calls = {"n": 0}

    def _fail(*a, **k):
        calls["n"] += 1
        return None

    monkeypatch.setattr(llm, "complete_vision", _fail)

    for _ in range(dw.VISION_FAIL_THRESHOLD):
        assert dw.vision_candidates("x.png") is None

    assert calls["n"] == dw.VISION_FAIL_THRESHOLD
    # 冷却期内：即使底层仍会失败，也不应再发起调用
    assert dw.vision_candidates("x.png") is None
    assert calls["n"] == dw.VISION_FAIL_THRESHOLD


def test_vision_circuit_breaker_resets_on_success(monkeypatch):
    from app import drawing as dw
    from app import llm

    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/openai/v1")
    monkeypatch.setattr(dw, "_VISION_FAILS", 2)
    monkeypatch.setattr(dw, "_VISION_COOLDOWN_UNTIL", 0.0)

    monkeypatch.setattr(
        llm, "complete_vision",
        lambda *a, **k: json.dumps({"plate": {"L": {"value": 10, "confidence": 0.9},
                                              "W": {"value": 5, "confidence": 0.9}}}),
    )
    assert dw.vision_candidates("x.png") is not None
    assert dw._VISION_FAILS == 0


# --------------------------------------------------------------------------- #
# OBS 降级
# --------------------------------------------------------------------------- #
def test_obs_fails_fast_without_config(monkeypatch):
    for k in ("OBS_ENDPOINT", "OBS_BUCKET", "OBS_AK", "OBS_SK"):
        monkeypatch.delenv(k, raising=False)

    res = obs.put_bytes(b"x", "a/b.txt")
    assert res["ok"] is False
    assert "OBS" in res["error"]

    assert obs.signed_url("a/b.txt") is None
    assert obs.probe()["ok"] is False
    assert obs.upload_files(["nope.bin"], prefix="p")["ok"] is False


def test_obs_object_key_respects_prefix(monkeypatch):
    monkeypatch.setenv("OBS_PREFIX", "evidence")
    assert obs.object_key("T-1/report.json") == "evidence/T-1/report.json"
    # 显式传空 prefix 表示不加前缀（env 里空值会回落到默认值）
    assert obs.object_key("T-1/report.json", prefix="") == "T-1/report.json"
    assert obs.object_key("/abs/path.json", prefix="p/") == "p/abs/path.json"


# --------------------------------------------------------------------------- #
# 证据包
# --------------------------------------------------------------------------- #
def test_evidence_stays_local_without_obs(tmp_path, monkeypatch):
    for k in ("OBS_ENDPOINT", "OBS_BUCKET", "OBS_AK", "OBS_SK"):
        monkeypatch.delenv(k, raising=False)

    result = {"state": "DONE", "budget": {"used": 1, "total": 5}}
    manifest = build_evidence("T-LOCAL", result, outdir=str(tmp_path))
    assert "storage" not in manifest, "未配置 OBS 时不应出现云端字段"
    assert verify_evidence(manifest["manifest_path"])["all_ok"] is True


def test_evidence_upload_requested_but_unconfigured_is_safe(tmp_path, monkeypatch):
    """显式要求上传但没凭据：本地证据包仍完整可校验。"""
    for k in ("OBS_ENDPOINT", "OBS_BUCKET", "OBS_AK", "OBS_SK"):
        monkeypatch.delenv(k, raising=False)

    result = {"state": "DONE"}
    manifest = build_evidence("T-UP", result, outdir=str(tmp_path), upload=True)
    assert verify_evidence(manifest["manifest_path"])["all_ok"] is True


# --------------------------------------------------------------------------- #
# 指标
# --------------------------------------------------------------------------- #
def test_metrics_emit_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "BUFFER_PATH", str(tmp_path / "metrics.jsonl"))

    metrics.emit("task.created", 1, dimensions={"source": "test"})
    metrics.emit("task.created", 1, dimensions={"source": "test"})
    metrics.timing("fix.duration", 12.0)
    metrics.timing("fix.duration", 30.0)
    metrics.emit("fix.duration.errors", 1)

    s = metrics.summary()
    assert s["counters"]["task.created"] == 2.0
    assert s["latency"]["fix.duration"]["count"] == 2
    assert s["latency"]["fix.duration"]["max_ms"] == 30.0
    assert s["errors"]["fix.duration.errors"] == 1.0
    assert s["error_rate"]["fix.duration"] == 0.5


def test_metrics_timer_records_on_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "BUFFER_PATH", str(tmp_path / "m.jsonl"))

    with pytest.raises(RuntimeError):
        with metrics.Timer("boom"):
            raise RuntimeError("x")

    s = metrics.summary()
    assert s["latency"]["boom"]["count"] == 1
    assert s["errors"]["boom.errors"] == 1.0


def test_metrics_push_without_ces_config(monkeypatch):
    monkeypatch.delenv("CES_AK", raising=False)
    monkeypatch.delenv("CES_SK", raising=False)
    res = metrics.push_ces([])
    assert res["ok"] is False


# --------------------------------------------------------------------------- #
# 异步任务
# --------------------------------------------------------------------------- #
def _wait(job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = get_job(job_id)
        if rec and rec["status"] in ("done", "failed"):
            return rec
        time.sleep(0.05)
    raise AssertionError(f"任务未在 {timeout}s 内结束: {job_id}")


def test_jobs_run_locally():
    job_id = jobs.submit("unit", lambda a, b=0: a + b, 2, b=3)
    rec = _wait(job_id)
    assert rec["status"] == "done"
    assert rec["result"] == 5
    assert rec["mode"] == "local"


def test_jobs_capture_failure():
    def boom():
        raise ValueError("故意失败")

    rec = _wait(jobs.submit("unit", boom))
    assert rec["status"] == "failed"
    assert "ValueError" in rec["error"]


def test_jobs_list_and_stats():
    job_id = jobs.submit("unit", lambda: "ok")
    _wait(job_id)
    # 注意：用 jobs.list_jobs（模块函数），不是 api.list_jobs（端点，返回 dict）
    assert any(j["job_id"] == job_id for j in jobs.list_jobs(limit=50))
    assert jobs.stats()["total"] >= 1


# --------------------------------------------------------------------------- #
# API 端点
# --------------------------------------------------------------------------- #
def test_api_meta_exposes_cloud():
    meta = get_meta()
    assert "cloud" in meta and "obs" in meta["cloud"]
    assert "metrics" in meta
    assert "jobs" in meta


def test_api_cloud_status_endpoint(monkeypatch):
    for k in ("OBS_ENDPOINT", "OBS_BUCKET", "OBS_AK", "OBS_SK"):
        monkeypatch.delenv(k, raising=False)
    res = cloud_status(probe=True)
    assert "status" in res
    assert res["obs_probe"]["ok"] is False


def test_api_async_fix_completes():
    tid = _tid()
    create_task(CreateTaskReq(with_defect=True, task_id=tid))

    started = fix_task_async(tid, FixReq(budget=5, mode="A1"))
    assert started["job_id"].startswith("J-")

    rec = _wait(started["job_id"])
    assert rec["status"] == "done"
    assert rec["result"]["state"] == "DONE"


def test_api_sync_fix_still_works():
    tid = _tid()
    create_task(CreateTaskReq(with_defect=True, task_id=tid))
    assert fix_task(tid, FixReq(budget=5, mode="A1"))["state"] == "DONE"


def test_api_export_without_obs_returns_paths():
    tid = _tid()
    create_task(CreateTaskReq(with_defect=True, task_id=tid))
    fix_task(tid, FixReq(budget=5, mode="A1"))
    out = export_task(tid)
    assert out["paths"]
    assert "storage" not in out


def test_api_evidence_endpoint():
    tid = _tid()
    create_task(CreateTaskReq(with_defect=True, task_id=tid))
    fix_task(tid, FixReq(budget=5, mode="A1"))
    res = evidence_task(tid)
    assert res["verification"]["all_ok"] is True
    assert "storage" not in res["manifest"]


def test_api_metrics_summary_endpoint():
    s = metrics_summary()
    assert "counters" in s and "latency" in s and "ces" in s


def test_api_job_404():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        get_job("J-does-not-exist")
    assert ei.value.status_code == 404


# --------------------------------------------------------------------------- #
# FunctionGraph handler（本地直调，验证契约）
# --------------------------------------------------------------------------- #
def test_functiongraph_handler_ping():
    import sys

    sys.path.insert(0, "functions")
    try:
        from handler import handler
    finally:
        sys.path.pop(0)

    assert handler({"kind": "ping"})["ok"] is True


def test_functiongraph_handler_runs_fix():
    import sys

    sys.path.insert(0, "functions")
    try:
        from handler import handler
    finally:
        sys.path.pop(0)

    from app.demo import plate_blueprint
    from app.parse import parse_blueprint

    spec = parse_blueprint(plate_blueprint(with_defect=True)).spec
    payload = {
        "kind": "fix",
        "payload": {
            "task_id": "T-FN-TEST",
            "spec": spec.to_dict(),
            "budget": 5,
            "auto_threshold": 0.55,
            "mode": "A1",
        },
    }
    # 走 HTTP 触发器形态（body 为 JSON 字符串）
    out = handler({"body": json.dumps(payload)})
    assert out["ok"] is True
    assert out["state"] == "DONE"
    assert out["runner"] == "functiongraph"
