"""异步任务队列：把长任务（修复闭环 / 建模导出 / 证据打包）放到后台执行。

为什么需要
----------
``/api/tasks/{id}/fix`` 是同步的：CadQuery 建模 + STEP/STL 导出可能耗时数秒到
数十秒，前端只能干等。本模块提供"提交 → 轮询"的异步接口：

    POST /api/tasks/{id}/fix/async   ->  {"job_id": "J-xxxxxxxx"}
    GET  /api/jobs/{job_id}          ->  {"status": "running|done|failed", ...}

两种执行模式
------------
- **local**（默认）：线程池执行，零依赖，适合本地演示。
- **functiongraph**：把同样的 payload POST 给函数工作流执行，适合云端部署。
  配置 ``FN_ENDPOINT`` 后自动启用；调用失败时返回 failed，由调用方决定是否重试。

状态机：queued → running → done | failed
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sourth-job")
_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}

# 只保留最近的任务，避免长期运行内存无限增长
MAX_JOBS = 100


def _trim_locked() -> None:
    """在持锁状态下裁掉最旧的记录。"""
    if len(_JOBS) <= MAX_JOBS:
        return
    oldest = sorted(_JOBS.items(), key=lambda kv: kv[1].get("created_ts", 0))
    for job_id, _ in oldest[: len(_JOBS) - MAX_JOBS]:
        _JOBS.pop(job_id, None)


def _update(job_id: str, **fields: Any) -> None:
    with _LOCK:
        rec = _JOBS.get(job_id)
        if rec is not None:
            rec.update(fields)


def _run(job_id: str, kind: str, func: Callable[..., Any] | None,
         args: tuple, kwargs: dict, remote: dict[str, Any] | None) -> None:
    """后台执行体：异常一律收敛为 failed，不向外抛。"""
    _update(job_id, status="running", started_at=time.time())
    t0 = time.perf_counter()
    mode = "local"

    try:
        if remote is not None:
            from . import fn

            mode = "functiongraph"
            res = fn.invoke(kind, remote)
            if not res.get("ok"):
                raise RuntimeError(res.get("error") or "FunctionGraph 调用失败")
            result = res.get("result")
        else:
            if func is None:
                raise RuntimeError("本地模式必须提供执行函数")
            result = func(*args, **kwargs)

        elapsed = (time.perf_counter() - t0) * 1000.0
        _update(job_id, status="done", result=result, mode=mode,
                finished_at=time.time(), elapsed_ms=round(elapsed, 2))
        _emit_metrics(kind, elapsed, ok=True)
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000.0
        _update(job_id, status="failed", error=f"{type(e).__name__}: {e}", mode=mode,
                finished_at=time.time(), elapsed_ms=round(elapsed, 2))
        _emit_metrics(kind, elapsed, ok=False)


def _emit_metrics(kind: str, elapsed_ms: float, *, ok: bool) -> None:
    """旁路上报指标；任何异常都不影响任务本身。"""
    try:
        from . import metrics

        dims = {"kind": kind, "status": "ok" if ok else "error"}
        metrics.emit("job.submitted", 1, dimensions=dims)
        metrics.timing("job.duration", elapsed_ms, dimensions=dims)
    except Exception:
        pass


def submit(kind: str, func: Callable[..., Any] | None = None, *args: Any,
           remote_payload: dict[str, Any] | None = None,
           **kwargs: Any) -> str:
    """提交一个后台任务，返回 job_id。

    remote_payload 非空且配置了 FN_ENDPOINT 时走函数工作流；
    否则用 func(*args, **kwargs) 在本地线程池执行。
    """
    job_id = f"J-{uuid.uuid4().hex[:8]}"
    rec: dict[str, Any] = {
        "job_id": job_id,
        "kind": kind,
        "status": "queued",
        "created_ts": time.time(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "started_at": None,
        "finished_at": None,
        "elapsed_ms": None,
        "mode": "functiongraph" if remote_payload is not None else "local",
        "result": None,
        "error": None,
    }
    with _LOCK:
        _JOBS[job_id] = rec
        _trim_locked()

    _EXECUTOR.submit(_run, job_id, kind, func, args, kwargs, remote_payload)
    return job_id


def get(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        rec = _JOBS.get(job_id)
        return dict(rec) if rec is not None else None


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    with _LOCK:
        recs = sorted(_JOBS.values(), key=lambda r: r.get("created_ts", 0), reverse=True)
        return [dict(r) for r in recs[:limit]]


def stats() -> dict[str, Any]:
    with _LOCK:
        recs = list(_JOBS.values())
    counts: dict[str, int] = {}
    for r in recs:
        counts[r.get("status", "unknown")] = counts.get(r.get("status", "unknown"), 0) + 1
    return {"total": len(recs), "by_status": counts, "max_jobs": MAX_JOBS}
