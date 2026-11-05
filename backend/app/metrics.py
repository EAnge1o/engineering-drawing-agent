"""云监控 CES 指标上报（可选）+ 本地指标缓冲。

用途
----
- 记录调用量、时延、错误率、修复轮次等运行指标
- 配置 CES 后批量上报为**自定义指标**，在云监控控制台做看板/告警
- 未配置时写入本地 JSONL 缓冲，``/api/metrics/summary`` 仍可提供同口径聚合，
  便于本地演示与 PPT 截图（不依赖云上环境）

设计约束
--------
1. **绝不抛出、绝不阻塞主流程**：指标是旁路，写盘失败也只是丢一条。
2. **默认全开**：本地缓冲始终记录（成本极低），CES 仅在配置齐备时启用。
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from .cloud import ces_config, ces_available

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUFFER_PATH = os.path.join(_BASE_DIR, "outputs", "metrics_buffer.jsonl")

# 缓冲区上限：超过后滚动截断，避免长期运行无限增长
MAX_BUFFER_LINES = 5000

_LOCK = threading.Lock()

# 已上报但尚未推送到 CES 的批次大小
CES_BATCH_SIZE = 20


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(BUFFER_PATH), exist_ok=True)


def _append(record: dict[str, Any]) -> None:
    """把一条指标追加到本地缓冲（失败静默）。"""
    try:
        _ensure_dir()
        with _LOCK:
            with open(BUFFER_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            _maybe_rotate()
    except Exception:
        pass


def _maybe_rotate() -> None:
    """缓冲超过上限时保留后半段（在持锁状态下调用）。"""
    try:
        if not os.path.exists(BUFFER_PATH):
            return
        with open(BUFFER_PATH, encoding="utf-8") as fh:
            lines = fh.readlines()
        if len(lines) <= MAX_BUFFER_LINES:
            return
        keep = lines[-MAX_BUFFER_LINES // 2:]
        with open(BUFFER_PATH, "w", encoding="utf-8") as fh:
            fh.writelines(keep)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 记录
# --------------------------------------------------------------------------- #
def emit(name: str, value: float = 1.0, *, unit: str = "Count",
         dimensions: dict[str, str] | None = None) -> None:
    """记录一条指标（计数/数值）。"""
    _append({
        "ts": time.time(),
        "name": name,
        "value": float(value),
        "unit": unit,
        "dims": dimensions or {},
    })


def timing(name: str, elapsed_ms: float, *, dimensions: dict[str, str] | None = None) -> None:
    """记录一次耗时（毫秒）。"""
    emit(name, round(float(elapsed_ms), 2), unit="ms", dimensions=dimensions)


class Timer:
    """上下文管理器：自动记录耗时，异常也会记录（带 status 维度）。"""

    def __init__(self, name: str, *, dimensions: dict[str, str] | None = None):
        self.name = name
        self.dims = dict(dimensions or {})
        self._t0 = 0.0

    def __enter__(self) -> "Timer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        elapsed = (time.perf_counter() - self._t0) * 1000.0
        dims = dict(self.dims)
        dims["status"] = "error" if exc_type else "ok"
        timing(self.name, elapsed, dimensions=dims)
        if exc_type:
            emit(f"{self.name}.errors", 1, dimensions=dims)
        return False  # 不吞异常


# --------------------------------------------------------------------------- #
# 聚合（供 /api/metrics/summary 与看板）
# --------------------------------------------------------------------------- #
def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = min(len(sorted_vals) - 1, max(0, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def read_records(limit: int = MAX_BUFFER_LINES) -> list[dict[str, Any]]:
    """读取最近的指标记录（失败返回空列表）。"""
    try:
        if not os.path.exists(BUFFER_PATH):
            return []
        with open(BUFFER_PATH, encoding="utf-8") as fh:
            lines = fh.readlines()[-limit:]
        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
    except Exception:
        return []


def summary(limit: int = MAX_BUFFER_LINES) -> dict[str, Any]:
    """把缓冲聚合成看板所需的结构：计数、时延分位、错误率。"""
    records = read_records(limit)
    counters: dict[str, float] = {}
    timings: dict[str, list[float]] = {}
    errors: dict[str, float] = {}

    for r in records:
        name = str(r.get("name", ""))
        value = float(r.get("value", 0) or 0)
        if r.get("unit") == "ms":
            timings.setdefault(name, []).append(value)
        elif name.endswith(".errors"):
            errors[name] = errors.get(name, 0.0) + value
        else:
            counters[name] = counters.get(name, 0.0) + value

    latency = {}
    for name, vals in timings.items():
        s = sorted(vals)
        latency[name] = {
            "count": len(s),
            "avg_ms": round(sum(s) / len(s), 2),
            "p50_ms": round(_percentile(s, 50), 2),
            "p95_ms": round(_percentile(s, 95), 2),
            "max_ms": round(s[-1], 2),
        }

    # 错误率：按"操作名"配对 <op>.errors 与 <op> 的调用次数
    # 调用次数优先取计数器；若该操作只有耗时记录，则用耗时样本数作分母
    error_rate = {}
    for name, err_count in errors.items():
        op = name[: -len(".errors")]
        total = counters.get(op, 0.0) or float(len(timings.get(op, [])))
        error_rate[op] = round(err_count / total, 4) if total else None

    return {
        "records": len(records),
        "counters": {k: round(v, 3) for k, v in sorted(counters.items())},
        "latency": latency,
        "errors": {k: round(v, 3) for k, v in sorted(errors.items())},
        "error_rate": error_rate,
        "buffer_path": BUFFER_PATH,
        "ces": status(),
    }


# --------------------------------------------------------------------------- #
# CES 上报
# --------------------------------------------------------------------------- #
def _build_ces_client():
    """构造 CES 客户端（依赖 huaweicloudsdkces）。"""
    from huaweicloudsdkcore.auth.credentials import BasicCredentials  # type: ignore
    from huaweicloudsdkces.v1 import CesClient  # type: ignore

    try:
        from huaweicloudsdkces.v1.region.ces_region import CesRegion  # type: ignore
    except Exception:  # pragma: no cover - 不同版本路径差异
        from huaweicloudsdkces.v1.region.ces_region import CesRegion  # type: ignore

    cfg = ces_config()
    creds = BasicCredentials(cfg["ak"], cfg["sk"], cfg["project_id"] or None)
    return CesClient.new_builder().with_credentials(creds).with_region(
        CesRegion.value_of(cfg["region"])
    ).build()


def _make_metric(name: str, value: float, unit: str, namespace: str):
    """构造 CES MetricInfo，兼容不同 SDK 版本的构造签名。"""
    from huaweicloudsdkces.v1 import MetricInfo  # type: ignore

    try:
        from huaweicloudsdkces.v1 import MetricsDimension  # type: ignore

        dims = [MetricsDimension(name="instance", value="sourth-cad-agent")]
    except Exception:  # pragma: no cover
        dims = []

    payload = {
        "metric_name": name,
        "value": float(value),
        "unit": "Count" if unit == "Count" else unit,
        "dimensions": dims,
    }
    for extra in ({"namespace": namespace}, {}):
        try:
            return MetricInfo(**{**payload, **extra})
        except Exception:
            continue
    return None


def push_ces(records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """把指标批量推送到 CES。未配置或 SDK 缺失时返回 ok=False（不抛异常）。"""
    if not ces_available():
        return {"ok": False, "reason": "CES 未配置或缺少 huaweicloudsdkces", "pushed": 0}

    cfg = ces_config()
    recs = records if records is not None else read_records()[-CES_BATCH_SIZE:]
    if not recs:
        return {"ok": True, "pushed": 0, "reason": "无待上报数据"}

    try:
        from huaweicloudsdkces.v1 import BatchMetricDataRequestBody  # type: ignore

        metrics = []
        for r in recs:
            m = _make_metric(str(r.get("name", "unknown")), float(r.get("value", 0) or 0),
                             str(r.get("unit", "Count")), cfg["namespace"])
            if m is not None:
                metrics.append(m)
        if not metrics:
            return {"ok": False, "reason": "MetricInfo 构造失败（SDK 版本不兼容）", "pushed": 0}

        client = _build_ces_client()
        client.batch_create_metric_data(BatchMetricDataRequestBody(metrics=metrics))
        return {"ok": True, "pushed": len(metrics), "namespace": cfg["namespace"]}
    except Exception as e:
        return {"ok": False, "reason": f"{type(e).__name__}: {e}", "pushed": 0}


# --------------------------------------------------------------------------- #
# 状态
# --------------------------------------------------------------------------- #
def status() -> dict[str, Any]:
    """指标子系统状态（供 /api/meta 展示）。"""
    cfg = ces_config()
    return {
        "buffer_path": BUFFER_PATH,
        "buffer_exists": os.path.exists(BUFFER_PATH),
        "ces_configured": ces_available(),
        "ces_namespace": cfg["namespace"],
        "ces_region": cfg["region"],
    }
