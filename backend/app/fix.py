"""局部修复：候选生成 → 影响分析 → 应用 → 回归验证 → 回滚。"""
from __future__ import annotations

import copy

from .graph import affected_constraints, affected_features
from .models import Fix, FixChange, Issue, Spec
from .propagate import set_param
from .rules import check_all, check_constraint


def propose_fix(spec: Spec, issue: Issue, g) -> Fix | None:
    """由问题生成候选修复（返回 None 表示无安全的自动修复候选）。"""
    c = spec.constraints.get(issue.constraint_id) if issue.constraint_id else None
    if c is None:
        return None

    changes: list[FixChange] = []

    if c.kind == "equality":
        pid = c.params[0]
        if c.target is not None and abs(spec.value(pid) - c.target) > c.tolerance:
            changes.append(FixChange(pid, spec.value(pid), c.target))

    elif c.kind == "max_value":
        pid = c.params[0]
        if c.target is not None and spec.value(pid) > c.target:
            changes.append(FixChange(pid, spec.value(pid), c.target))

    elif c.kind == "geom_positive":
        pid = c.params[0]
        if spec.value(pid) <= 0:
            changes.append(FixChange(pid, spec.value(pid), abs(spec.value(pid)) or 1.0))

    elif c.kind == "hole_inside":
        xp, yp, Lp, Wp = c.params[:4]
        x, y, L, W = (spec.value(p) for p in (xp, yp, Lp, Wp))
        d = spec.params["hole.d"].value if "hole.d" in spec.params else 0.0
        base_min = c.target if c.target is not None else 0.0
        m_min = max(base_min, d / 2.0)
        # 修复目标优先采用图纸声明的边距参数（证据融合），否则用最小合法边距
        m_pref = m_min
        for qid, q in spec.params.items():
            if (qid == "margin" or qid.endswith(".margin")) and q.kind != "derived":
                m_pref = max(m_min, q.value)
                break

        left_bad = x < m_min
        right_bad = (L - x) < m_min
        bottom_bad = y < m_min
        top_bad = (W - y) < m_min
        # 同一轴两侧同时越界 = 该尺寸本身不可满足，需人工确认（避免无效候选烧预算）
        if (left_bad and right_bad) or (bottom_bad and top_bad):
            return None

        if left_bad:
            changes.append(FixChange(xp, x, m_pref))
        elif right_bad:
            changes.append(FixChange(xp, x, L - m_pref))
        if bottom_bad:
            changes.append(FixChange(yp, y, m_pref))
        elif top_bad:
            changes.append(FixChange(yp, y, W - m_pref))

    if not changes:
        return None

    changed = [ch.param for ch in changes]
    return Fix(
        fix_id=f"fix::{issue.id}",
        issue_id=issue.id,
        changes=changes,
        affected_features=sorted(affected_features(g, changed)),
        affected_constraints=sorted(affected_constraints(g, changed)),
    )


def _restore(dst: Spec, src: Spec) -> None:
    dst.params = copy.deepcopy(src.params)
    dst.features = copy.deepcopy(src.features)
    dst.constraints = copy.deepcopy(src.constraints)


def apply_fix(spec: Spec, fix: Fix) -> Fix:
    """应用修复；任一步失败即整体回滚，且不向外抛出（避免 spec 半污染）。"""
    snapshot = spec.clone()
    try:
        for ch in fix.changes:
            set_param(spec, ch.param, ch.new)
    except Exception as e:
        _restore(spec, snapshot)
        fix.rolled_back = True
        fix.regression_passed = False
        fix.note = f"apply 失败已整体回滚：{type(e).__name__}: {e}"
    return fix


def is_resolved(spec: Spec, constraint_id: str | None) -> bool:
    if not constraint_id:
        return False
    c = spec.constraints.get(constraint_id)
    return c is not None and check_constraint(spec, c) is None


def regression_check(spec: Spec, baseline_ids: set[str]) -> set[str]:
    """返回修复后新出现的失败约束（回归错误）。"""
    after = {i.constraint_id for i in check_all(spec) if i.constraint_id}
    return {c for c in after if c not in baseline_ids}