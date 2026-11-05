"""REST API 层（FastAPI）。

内存任务仓库 + SQLite 持久化。端点覆盖 PRD 第 8 节的接口概要。
"""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from . import cloud, jobs, metrics, obs
from .audit import audit
from .cad import cadquery_available, export_step_stl, geometry_summary
from .demo import plate_blueprint
from .drawing import parse_drawing
from .evidence import build_evidence, verify_evidence
from .llm import explain_run, llm_available
from .models import AutoMode, Spec
from .parse import parse_blueprint
from .state import run_repair_loop
from .store import list_tasks, load_task, save_task

# 路径以 backend/ 为基准，避免随进程 CWD 漂移
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB = os.path.join(_BASE_DIR, "agent.db")
_UPLOADS = os.path.join(_BASE_DIR, "uploads")
_OUTPUTS = os.path.join(_BASE_DIR, "outputs")
_EVIDENCE = os.path.join(_OUTPUTS, "evidence")
_TASKS: dict[str, dict[str, Any]] = {}

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".bmp"}
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


class CreateTaskReq(BaseModel):
    with_defect: bool = False
    preference: Literal["auto", "assisted", "manual"] = "auto"
    budget: int = Field(default=5, ge=1, le=10)
    auto_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    task_id: str | None = None


class FixReq(BaseModel):
    budget: int | None = Field(default=None, ge=1, le=10)
    mode: AutoMode = AutoMode.A1
    auto_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


def _next_task_id() -> str:
    nums = [int(k[2:]) for k in _TASKS if k.startswith("T-") and k[2:].isdigit()]
    return f"T-{max(nums, default=0) + 1:03d}"


def restore_tasks() -> int:
    """启动时从 SQLite 回灌（含 Spec），使重启后任务可继续使用。"""
    restored = 0
    for row in list_tasks(_DB):
        tid = row.get("task_id") or row.get("id")
        if not tid or tid in _TASKS:
            continue
        payload = load_task(tid, _DB)
        if not payload:
            continue
        spec_data = payload.get("spec")
        try:
            spec = Spec.from_dict(spec_data) if spec_data else None
        except Exception:
            spec = None
        if spec is None:
            continue
        _TASKS[tid] = {
            "task_id": tid,
            "spec": spec,
            "parse": None,
            "budget": (payload.get("budget") or {}).get("total", 5),
            "auto_threshold": 0.55,
            "state": payload.get("state", row.get("state", "RESTORED")),
            "result": {k: v for k, v in payload.items() if k != "spec"},
            "restored": True,
        }
        restored += 1
    return restored


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    restore_tasks()
    yield


app = FastAPI(title="工程图纸建模与自纠错 Agent", version="0.1.0", lifespan=_lifespan)


def _issues_payload(spec: Spec) -> list[dict[str, Any]]:
    return [
        {
            "id": i.id,
            "code": i.code,
            "layer": i.layer.value,
            "severity": i.severity.value,
            "confidence": i.confidence,
            "location": i.location,
            "evidence": i.evidence,
            "fixable": i.fixable,
            "constraint_id": i.constraint_id,
            "fix_hint": i.fix_hint,
        }
        for i in audit(spec)
    ]


def _get(tid: str) -> dict[str, Any]:
    if tid not in _TASKS:
        raise HTTPException(status_code=404, detail=f"任务不存在: {tid}")
    return _TASKS[tid]


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.post("/api/tasks")
def create_task(req: CreateTaskReq) -> dict[str, Any]:
    tid = req.task_id or _next_task_id()
    if tid in _TASKS:
        raise HTTPException(status_code=409, detail=f"任务已存在: {tid}")
    with metrics.Timer("parse.duration", dimensions={"source": "blueprint"}):
        res = parse_blueprint(plate_blueprint(with_defect=req.with_defect), preference=req.preference)
    metrics.emit("task.created", dimensions={"source": "blueprint"})
    _TASKS[tid] = {
        "task_id": tid,
        "spec": res.spec,
        "parse": res.to_dict(),
        "budget": req.budget,
        "auto_threshold": req.auto_threshold,
        "state": "PARSED",
        "result": None,
    }
    return {
        "task_id": tid,
        "state": "PARSED",
        "parse": res.to_dict(),
        "issues": _issues_payload(res.spec),
    }


def _create_task_from_drawing_file(
    path: str,
    *,
    preference: str = "auto",
    budget: int = 5,
    auto_threshold: float = 0.55,
    task_id: str | None = None,
    use_vision: bool | None = None,
) -> dict[str, Any]:
    """由真实图纸文件（PDF/PNG）创建任务。

    use_vision=None 表示自动：配置了 MaaS 多模态即启用，否则走纯确定性路径。
    """
    with metrics.Timer("parse.duration", dimensions={"source": "drawing"}):
        res = parse_drawing(path, preference=preference, use_vision=use_vision)
    vision_used = bool((res.drawing or {}).get("vision"))
    metrics.emit("task.created", dimensions={
        "source": "drawing",
        "vision": "on" if vision_used else "off",
    })
    tid = task_id or _next_task_id()
    if tid in _TASKS:
        raise HTTPException(status_code=409, detail=f"任务已存在: {tid}")
    _TASKS[tid] = {
        "task_id": tid,
        "spec": res.spec,
        "parse": res.to_dict(),
        "budget": budget,
        "auto_threshold": auto_threshold,
        "state": "PARSED",
        "result": None,
        "source_file": os.path.basename(path),
    }
    return {
        "task_id": tid,
        "state": "PARSED",
        "source_file": os.path.basename(path),
        "parse": res.to_dict(),
        "issues": _issues_payload(res.spec),
    }


@app.post("/api/tasks/from-drawing")
async def create_task_from_drawing(
    file: UploadFile = File(...),
    preference: Literal["auto", "assisted", "manual"] = Form("auto"),
    budget: int = Form(5, ge=1, le=10),
    auto_threshold: float = Form(0.55, ge=0.0, le=1.0),
    use_vision: bool | None = Form(None),
) -> dict[str, Any]:
    """上传图纸（PDF/PNG）→ 解析 → 创建任务。

    - 先校验扩展名（422）与大小（413），非法输入不再裸 500
    - 重活（OCR / 子进程）交由线程池执行，不阻塞事件循环
    """
    raw_name = os.path.basename(file.filename or "drawing.pdf")
    ext = os.path.splitext(raw_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的文件类型 {ext or '(无扩展名)'}；支持 {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"文件过大：>{MAX_UPLOAD_BYTES // (1024 * 1024)}MB")

    os.makedirs(_UPLOADS, exist_ok=True)
    dest = os.path.join(_UPLOADS, f"{uuid.uuid4().hex[:8]}_{raw_name}")
    with open(dest, "wb") as fh:
        fh.write(data)

    try:
        return await asyncio.to_thread(
            _create_task_from_drawing_file,
            dest, preference=preference, budget=budget, auto_threshold=auto_threshold,
            use_vision=use_vision,
        )
    except HTTPException:
        raise
    except (RuntimeError, ValueError, OSError) as e:
        raise HTTPException(status_code=422, detail=f"图纸解析失败：{e}")


@app.get("/api/tasks")
def get_tasks() -> dict[str, Any]:
    if _TASKS:
        return {"tasks": [{"task_id": t["task_id"], "state": t["state"]} for t in _TASKS.values()]}
    # 内存为空（刚重启且尚未回灌）：返回磁盘档案并标注 stale
    return {"tasks": [
        {**r, "task_id": r.get("task_id") or r.get("id"), "stale": True}
        for r in list_tasks(_DB)
    ]}


@app.get("/api/tasks/{tid}")
def get_task(tid: str) -> dict[str, Any]:
    t = _get(tid)
    return {"task_id": tid, "state": t["state"], "parse": t["parse"]}


@app.get("/api/tasks/{tid}/issues")
def get_issues(tid: str) -> dict[str, Any]:
    return {"issues": _issues_payload(_get(tid)["spec"])}


@app.get("/api/tasks/{tid}/model")
def get_model(tid: str) -> dict[str, Any]:
    return geometry_summary(_get(tid)["spec"])


def _do_fix(tid: str, req: FixReq) -> dict[str, Any]:
    """执行修复闭环（同步与异步端点共用）。"""
    t = _get(tid)
    budget = req.budget if req.budget is not None else t["budget"]
    thr = req.auto_threshold if req.auto_threshold is not None else t["auto_threshold"]
    # 修复前快照，用于"修复前后对比"
    t["before_values"] = {pid: p.value for pid, p in t["spec"].params.items()}
    t["before_issues"] = _issues_payload(t["spec"])

    with metrics.Timer("fix.duration", dimensions={"mode": req.mode.value}):
        result = run_repair_loop(
            t["spec"], budget=budget, auto_threshold=thr,
            mode=req.mode, task_id=tid,
        )
    t["result"] = result
    t["state"] = result["state"]
    save_task(tid, result, spec=t["spec"], state=result["state"], db=_DB)

    metrics.emit("fix.completed", dimensions={"state": str(result.get("state"))})
    metrics.emit("issue.detected", len(result.get("issues") or []))
    metrics.emit("fix.rounds", (result.get("budget") or {}).get("used", 0))
    metrics.emit("fix.remaining", len(result.get("remaining") or []))
    return result


@app.post("/api/tasks/{tid}/fix")
def fix_task(tid: str, req: FixReq) -> dict[str, Any]:
    return _do_fix(tid, req)


@app.post("/api/tasks/{tid}/fix/async")
def fix_task_async(tid: str, req: FixReq) -> dict[str, Any]:
    """异步修复：立即返回 job_id，前端轮询 GET /api/jobs/{job_id}。

    配置了 FN_ENDPOINT 时把任务交给函数工作流执行（Serverless 异步化）。
    """
    t = _get(tid)  # 任务不存在则尽早 404

    remote_payload: dict[str, Any] | None = None
    if cloud.fn_available():
        remote_payload = {
            "task_id": tid,
            "spec": t["spec"].to_dict(),
            "budget": req.budget if req.budget is not None else t["budget"],
            "auto_threshold": req.auto_threshold if req.auto_threshold is not None else t["auto_threshold"],
            "mode": req.mode.value,
        }

    job_id = jobs.submit("fix", _do_fix, tid, req, remote_payload=remote_payload)
    return {
        "job_id": job_id,
        "task_id": tid,
        "mode": "functiongraph" if remote_payload else "local",
        "poll": f"/api/jobs/{job_id}",
    }


@app.get("/api/tasks/{tid}/report")
def get_report(tid: str) -> dict[str, Any]:
    t = _get(tid)
    if t["result"] is None:
        raise HTTPException(status_code=409, detail="尚未执行修复")
    return {"task_id": tid, "result": t["result"], "model": geometry_summary(t["spec"])}


@app.post("/api/tasks/{tid}/export")
def export_task(tid: str, upload: bool | None = None) -> dict[str, Any]:
    """导出 STEP/STL。upload=true 或已配置 OBS 时，同时上传产物并返回预签名链接。"""
    t = _get(tid)
    with metrics.Timer("export.duration"):
        paths = export_step_stl(t["spec"], f"outputs/{tid}")

    files = [p for p in paths.values() if os.path.isfile(p)]
    payload: dict[str, Any] = {"paths": paths}

    do_upload = cloud.obs_available() if upload is None else upload
    if do_upload and files:
        payload["storage"] = obs.upload_files(files, prefix=f"{tid}/export")
    return payload

@app.get("/api/meta")
def get_meta() -> dict[str, Any]:
    """能力探测：前端据此决定是否展示增强功能。"""
    from .parse import THRESH_HIGH, THRESH_LOW

    return {
        "llm_available": llm_available(),
        "cadquery_available": cadquery_available(),
        "thresholds": {"high": THRESH_HIGH, "low": THRESH_LOW},
        # 华为云服务接入状态（未配置时为 available=False，不影响主闭环）
        "cloud": cloud.status(),
        "metrics": metrics.status(),
        "jobs": jobs.stats(),
    }


@app.get("/api/cloud/status")
def cloud_status(probe: bool = False) -> dict[str, Any]:
    """华为云服务状态。probe=true 时额外做一次 OBS 连通性检查（会发起网络请求）。"""
    payload: dict[str, Any] = {"status": cloud.status()}
    if probe:
        payload["obs_probe"] = obs.probe()
    return payload


@app.get("/api/metrics/summary")
def metrics_summary(limit: int = 5000) -> dict[str, Any]:
    """指标看板数据：调用量、时延分位、错误率（本地缓冲聚合，无需云环境）。"""
    return metrics.summary(limit=max(1, min(limit, 5000)))


@app.post("/api/metrics/push")
def metrics_push() -> dict[str, Any]:
    """把本地缓冲的指标批量推送到 CES（需配置 CES_AK/CES_SK 与 SDK）。"""
    return metrics.push_ces()


@app.get("/api/jobs")
def list_jobs(limit: int = 20) -> dict[str, Any]:
    return {"jobs": jobs.list_jobs(limit=max(1, min(limit, 100)))}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    rec = jobs.get(job_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}")
    return rec


@app.get("/api/tasks/{tid}/compare")
def compare_task(tid: str) -> dict[str, Any]:
    """修复前后对比：参数差异 + 问题集差异。"""
    t = _get(tid)
    if t["result"] is None:
        raise HTTPException(status_code=409, detail="尚未执行修复")

    before_values = t.get("before_values", {})
    after_values = t["result"].get("final_values", {})
    changed = [
        {"param": pid, "before": before_values[pid], "after": val,
         "delta": round(val - before_values[pid], 4)}
        for pid, val in after_values.items()
        if pid in before_values and abs(before_values[pid] - val) > 1e-9
    ]
    before_ids = {i["constraint_id"] for i in t.get("before_issues", []) if i.get("constraint_id")}
    after_ids = {i["constraint_id"] for i in _issues_payload(t["spec"]) if i.get("constraint_id")}

    return {
        "task_id": tid,
        "changed_params": changed,
        "resolved": sorted(before_ids - after_ids),
        "remaining": sorted(after_ids),
        "before_issue_count": len(before_ids),
        "after_issue_count": len(after_ids),
    }


@app.post("/api/tasks/{tid}/explain")
def explain_task(tid: str, use_llm: bool = True) -> dict[str, Any]:
    """审查—修复说明（有模型用模型，无模型退化为确定性摘要）。"""
    t = _get(tid)
    if t["result"] is None:
        raise HTTPException(status_code=409, detail="尚未执行修复")
    return explain_run(t["result"], use_llm=use_llm)


@app.post("/api/tasks/{tid}/evidence")
def evidence_task(tid: str, upload: bool | None = None) -> dict[str, Any]:
    """生成并校验证据包（含文件 SHA-256 清单）。

    upload=None 表示自动：配置了 OBS 就同步上传，manifest 会记录对象 key 与 ETag。
    """
    t = _get(tid)
    if t["result"] is None:
        raise HTTPException(status_code=409, detail="尚未执行修复")

    outdir = f"{_OUTPUTS}/{tid}"
    os.makedirs(outdir, exist_ok=True)
    with metrics.Timer("export.duration", dimensions={"kind": "evidence"}):
        extra = [p for p in export_step_stl(t["spec"], outdir).values() if os.path.isfile(p)]

    with metrics.Timer("evidence.duration"):
        manifest = build_evidence(
            tid, t["result"], outdir=_EVIDENCE,
            extra_files=extra, spec_snapshot=t["spec"].to_dict(),
            upload=upload,
        )
    verification = verify_evidence(manifest["manifest_path"])
    metrics.emit("evidence.generated", dimensions={"ok": str(verification.get("all_ok"))})

    return {
        "manifest": {k: v for k, v in manifest.items() if k != "manifest_path"},
        "verification": verification,
    }