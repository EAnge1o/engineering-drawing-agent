"""FunctionGraph 函数工作流调用客户端（可选）。

用途：把"建模 / 导出 STEP-STL / 证据打包"这类秒级到分钟级的长任务放到
函数工作流上执行，API 侧只负责提交与轮询，避免同步请求被拖死。

约定
----
- 配置 ``FN_ENDPOINT`` 即启用（函数需暴露 HTTP 触发器，接收/返回 JSON）
- 请求体：``{"kind": "...", "payload": {...}}``
- 响应体：函数直接返回结果 JSON（本客户端原样透传）
- 可选 ``FN_TOKEN``：以 ``Authorization: Bearer <token>`` 传递

未配置或调用失败时返回 ``ok=False``，调用方负责回退到本地执行。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .cloud import fn_config


def fn_available() -> bool:
    return bool(fn_config()["endpoint"])


def invoke(kind: str, payload: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
    """调用函数工作流。返回 {ok, status, result} 或 {ok:False, error}。"""
    cfg = fn_config()
    endpoint = cfg["endpoint"]
    if not endpoint:
        return {"ok": False, "error": "FunctionGraph 未配置（缺少 FN_ENDPOINT）"}

    body = json.dumps({"kind": kind, "payload": payload}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"

    req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout or cfg["timeout"]) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
        try:
            parsed = json.loads(raw) if raw else {}
        except ValueError:
            parsed = {"raw": raw}
        return {"ok": 200 <= status < 300, "status": status, "result": parsed}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        return {"ok": False, "status": e.code, "error": f"HTTP {e.code}: {detail}"}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def status() -> dict[str, Any]:
    cfg = fn_config()
    return {
        "configured": fn_available(),
        "endpoint_set": bool(cfg["endpoint"]),
        "timeout": cfg["timeout"],
        "token_set": bool(cfg["token"]),
        "env_hint": os.environ.get("FN_ENDPOINT", ""),
    }
