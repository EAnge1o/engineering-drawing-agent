"""FunctionGraph 函数入口（可选部署）。

部署方式
--------
1. 把 ``backend/`` 整个目录（含 ``app/``）打包为 zip，作为函数代码上传；
2. 函数入口填写 ``handler.handler``；
3. 运行时选 Python 3.10+，超时建议 ≥ 60s，内存 ≥ 512MB；
4. 配置 HTTP 触发器，把触发器 URL 填入后端的 ``FN_ENDPOINT``。

调用约定
--------
请求体（由 ``app/fn.py`` 发出）::

    {"kind": "fix", "payload": {"task_id": "...", "spec": {...}, "budget": 5,
                                "auto_threshold": 0.55, "mode": "A1"}}

响应体：直接返回修复结果 JSON（与 ``run_repair_loop`` 的输出一致）。

说明
----
- 该函数**无状态**：Spec 由 payload 传入，结果由调用方落库。
- 几何内核（CadQuery）若未打进函数包，会自动退化为确定性几何摘要，
  闭环仍然成立（见 ``app/cad.py``）。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

# FunctionGraph 把代码放在 /opt/ 或当前目录；确保能 import app 包
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)          # backend/
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _parse_event(event: Any) -> dict[str, Any]:
    """兼容 HTTP 触发器（body 为字符串）与直接 JSON 调用。"""
    if isinstance(event, dict):
        body = event.get("body", event)
        if isinstance(body, str):
            try:
                return json.loads(body)
            except ValueError:
                return {}
        return body if isinstance(body, dict) else {}
    if isinstance(event, str):
        try:
            return json.loads(event)
        except ValueError:
            return {}
    return {}


def handler(event: Any, context: Any = None) -> dict[str, Any]:
    """FunctionGraph 入口：按 kind 分发到具体动作。"""
    req = _parse_event(event)
    kind = str(req.get("kind") or "fix")
    payload = req.get("payload") or {}

    try:
        if kind == "fix":
            return _run_fix(payload)
        if kind == "ping":
            return {"ok": True, "kind": "ping", "service": "sourth-cad-agent"}
        return {"ok": False, "error": f"未知的 kind: {kind}"}
    except Exception as e:  # 函数内异常必须以结构化方式返回，便于调用方判断
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _run_fix(payload: dict[str, Any]) -> dict[str, Any]:
    """在函数内跑一次修复闭环。"""
    from app.models import AutoMode, Spec
    from app.state import run_repair_loop

    spec_data = payload.get("spec") or {}
    if not spec_data:
        return {"ok": False, "error": "payload.spec 缺失"}

    spec = Spec.from_dict(spec_data)
    mode_raw = str(payload.get("mode") or "A1")
    try:
        mode = AutoMode(mode_raw)
    except ValueError:
        mode = AutoMode.A1

    result = run_repair_loop(
        spec,
        budget=int(payload.get("budget") or 5),
        auto_threshold=float(payload.get("auto_threshold") or 0.55),
        mode=mode,
        task_id=str(payload.get("task_id") or "T-FN"),
    )
    result["ok"] = True
    result["runner"] = "functiongraph"
    return result
