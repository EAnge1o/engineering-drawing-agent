"""确定性规则引擎。

对 Spec 中每条 Constraint 逐项判定，产出 Issue（带位置/证据/严重度/置信度）。
所有判定均为确定性数值计算，不依赖大模型。
"""
from __future__ import annotations

import math

from .models import (
    Constraint,
    Issue,
    IssueLayer,
    Severity,
    Spec,
)


_REQUIRED_PARAMS = {
    "geom_positive": 1,
    "equality": 1,
    "max_value": 1,
    "max_value_ratio": 2,
    "hole_inside": 4,
    "spacing_min": 4,
    "geom_valid": 0,
}


def _min_conf(spec: Spec, params: list[str]) -> float:
    confs = [spec.params[p].confidence for p in params if p in spec.params]
    return min(confs) if confs else 0.5


def _hole_diameter(spec: Spec) -> float:
    p = spec.params.get("hole.d")
    return p.value if p is not None else 0.0


def _make_issue(c: Constraint, spec: Spec, evidence: list[str], hint: dict | None = None) -> Issue:
    return Issue(
        id=f"issue::{c.id}",
        code=c.kind,
        layer=c.layer,
        severity=c.severity,
        confidence=_min_conf(spec, c.params),
        location={"constraint": c.id, "params": list(c.params), "features": list(c.features)},
        evidence=evidence,
        fixable=c.fixable,
        constraint_id=c.id,
        fix_hint=hint,
    )


def check_constraint(spec: Spec, c: Constraint) -> Issue | None:
    """检查单条约束，返回 Issue 或 None（通过）。"""
    # 约束引用的参数缺失时跳过（图纸解析可能只识别出部分特征）
    if any(pid not in spec.params for pid in c.params):
        return None
    # 参数个数不足时跳过，避免 IndexError / 解包错误
    if len(c.params) < _REQUIRED_PARAMS.get(c.kind, 0):
        return None

    v = spec.params
    kind = c.kind

    if kind == "geom_positive":
        pid = c.params[0]
        val = spec.value(pid)
        if val <= 0:
            return _make_issue(c, spec, [f"{pid}={val} <= 0"], {"param": pid, "suggest": abs(val) or 1.0})

    elif kind == "equality":
        pid = c.params[0]
        val = spec.value(pid)
        target = c.target if c.target is not None else val
        if abs(val - target) > c.tolerance:
            return _make_issue(
                c, spec, [f"{pid}={val} 与期望 {target} 偏差 {abs(val - target):.4g} > 容差 {c.tolerance}"],
                {"param": pid, "suggest": target},
            )

    elif kind == "max_value":
        pid = c.params[0]
        val = spec.value(pid)
        target = c.target if c.target is not None else val
        if val > target + c.tolerance:
            return _make_issue(c, spec, [f"{pid}={val} > 上限 {target}"], {"param": pid, "suggest": target})

    elif kind == "max_value_ratio":
        pid, other = c.params[0], c.params[1]
        ratio = c.target if c.target is not None else 1.0
        val, base = spec.value(pid), spec.value(other)
        if base <= 0 or val > ratio * base + c.tolerance:
            limit = ratio * base
            return _make_issue(
                c, spec, [f"{pid}={val} > {ratio}×{other}({base})={limit:.4g}"],
                {"param": pid, "suggest": limit},
            )

    elif kind == "hole_inside":
        hx, hy, L, W = (spec.value(p) for p in c.params[:4])
        base_m = c.target if c.target is not None else 0.0
        d = _hole_diameter(spec)
        # 孔心到板边至少半个孔径，保证"孔完整落在板内"（而非仅孔心在板内）
        m = max(base_m, d / 2.0)
        margins = {"left": hx, "right": L - hx, "bottom": hy, "top": W - hy}
        bad = {k: mv for k, mv in margins.items() if mv < m - c.tolerance}
        if bad:
            worst = min(bad, key=bad.get)
            need = m - bad[worst]
            return _make_issue(
                c, spec,
                [f"孔位 ({hx},{hy}) 在 {L}×{W} 板上，{worst} 边距 {bad[worst]:.4g} < 最小 {m:.4g}"
                 f"（边距基准 {base_m:.4g}，孔径 {d:.4g}）"],
                {"param": c.params[0] if worst in ("left", "right") else c.params[1],
                 "delta": need, "side": worst, "bad_sides": sorted(bad)},
            )

    elif kind == "spacing_min":
        ax, ay, bx, by = (spec.value(p) for p in c.params[:4])
        dist = math.hypot(ax - bx, ay - by)
        m = c.target if c.target is not None else 0.0
        if dist < m - c.tolerance:
            return _make_issue(
                c, spec,
                [f"孔间距 {dist:.4g} < 最小 {m}（({ax},{ay})↔({bx},{by})）"],
                {"params": [c.params[0], c.params[1]], "delta": m - dist},
            )

    elif kind == "geom_valid":
        return None

    else:
        return None

    return None


def check_all(spec: Spec) -> list[Issue]:
    """运行全部确定性检查。"""
    issues: list[Issue] = []
    for c in spec.constraints.values():
        issue = check_constraint(spec, c)
        if issue is not None:
            issues.append(issue)
    return issues


def summarize(issues: list[Issue]) -> dict[str, int]:
    counts: dict[str, int] = {"total": len(issues)}
    for s in Severity:
        counts[s.value] = sum(1 for i in issues if i.severity == s)
    for layer in IssueLayer:
        counts[layer.value] = sum(1 for i in issues if i.layer == layer)
    return counts