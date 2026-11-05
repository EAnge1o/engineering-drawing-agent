"""几何内核适配层（CadQuery 可选）。

CadQuery 可用时构建真实实体并导出 STEP/STL；不可用时退化为确定性几何摘要，
保证"审查/修复/验证闭环"不依赖几何内核即可运行。

孔数量由 Spec 中**实际存在的** hole.x{i}/hole.y{i} 决定，不假设固定 4 孔
（真实图纸可能只识别出 2~3 个孔）。
"""
from __future__ import annotations

import importlib
import itertools
import json
import math
import os
from typing import Any

from .models import Spec

_CQ_IMPORT_CACHE: bool | None = None


def cadquery_available() -> bool:
    """真实尝试导入一次并缓存结果（仅 find_spec 无法发现"装坏"的内核）。"""
    global _CQ_IMPORT_CACHE
    if _CQ_IMPORT_CACHE is None:
        try:
            importlib.import_module("cadquery")
            _CQ_IMPORT_CACHE = True
        except Exception:
            _CQ_IMPORT_CACHE = False
    return _CQ_IMPORT_CACHE


def hole_ids(spec: Spec) -> list[int]:
    """返回实际存在的孔序号（连续到第一个缺失为止）。"""
    ids: list[int] = []
    for i in itertools.count(1):
        if f"hole.x{i}" in spec.params and f"hole.y{i}" in spec.params:
            ids.append(i)
        else:
            break
    return ids


def _hole_diameter(spec: Spec) -> float | None:
    p = spec.params.get("hole.d")
    return p.value if p is not None else None


def geometry_summary(spec: Spec) -> dict[str, Any]:
    """不依赖内核的确定性几何摘要（包围盒 / 体积 / 孔位）。"""
    L = spec.value("plate.L")
    W = spec.value("plate.W")
    T = spec.value("plate.T")
    d = _hole_diameter(spec)

    holes = [
        {"id": f"hole_h{i}", "x": spec.value(f"hole.x{i}"),
         "y": spec.value(f"hole.y{i}"), "d": d}
        for i in hole_ids(spec)
    ]
    hole_area = len(holes) * math.pi * (d / 2) ** 2 if d else 0.0
    volume = L * W * T - hole_area * T

    summary: dict[str, Any] = {
        "kernel": "cadquery" if cadquery_available() else "none",
        "bbox": {"length": L, "width": W, "height": T},
        "volume": round(volume, 4),
        "hole_count": len(holes),
        "holes": holes,
    }
    if d is None:
        summary["note"] = "未识别孔直径（hole.d 缺失），体积按无孔计算"
    return summary


def build_plate(spec: Spec):
    """用 CadQuery 构建真实实体；内核不可用时返回 None。"""
    if not cadquery_available():
        return None
    import cadquery as cq

    L = spec.value("plate.L")
    W = spec.value("plate.W")
    T = spec.value("plate.T")
    r = spec.params["fillet.r"].value if "fillet.r" in spec.params else 0.0
    d = _hole_diameter(spec)

    wp = cq.Workplane("XY").box(L, W, T)
    if r > 0:
        try:
            wp = wp.edges("|Z").fillet(min(r, min(L, W) / 2 - 1e-3))
        except Exception:
            pass
    if d:
        for i in hole_ids(spec):
            wp = (wp.faces(">Z").workplane()
                  .pushPoints([(spec.value(f"hole.x{i}") - L / 2,
                                spec.value(f"hole.y{i}") - W / 2)])
                  .hole(d))
    return wp


def export_step_stl(spec: Spec, outdir: str) -> dict[str, str]:
    """导出模型。内核不可用时仅输出几何摘要 JSON。"""
    os.makedirs(outdir, exist_ok=True)
    wp = build_plate(spec)
    paths: dict[str, str] = {}

    if wp is None:
        paths["kernel_warning"] = "CadQuery 未安装，仅输出几何摘要 JSON"
        p = os.path.join(outdir, "model_summary.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(geometry_summary(spec), fh, ensure_ascii=False, indent=2)
        paths["json"] = p
        return paths

    from cadquery import exporters

    step = os.path.join(outdir, "model.step")
    stl = os.path.join(outdir, "model.stl")
    exporters.export(wp, step)
    exporters.export(wp, stl)
    paths["step"] = step
    paths["stl"] = stl
    return paths