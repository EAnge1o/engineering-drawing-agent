"""Agent 显式状态机：审查 → 修复 → 回归验证 → 回滚/停止。

状态：IDLE → AUDITING → FIXING → VERIFYING → DONE / STOPPED。
约束：预算是硬限制；低置信度或不可自动修复的问题进入人工确认队列。
"""
from __future__ import annotations

import copy
from dataclasses import asdict
from typing import Any

from .audit import audit
from .fix import apply_fix, is_resolved, propose_fix, regression_check
from .graph import build_graph
from .models import AutoMode, Severity, Spec, Task

_SEV_RANK = {Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1}


def _restore(dst: Spec, src: Spec) -> None:
    dst.params = copy.deepcopy(src.params)
    dst.features = copy.deepcopy(src.features)
    dst.constraints = copy.deepcopy(src.constraints)


def run_repair_loop(
    spec: Spec,
    *,
    budget: int = 5,
    auto_threshold: float = 0.55,
    mode: AutoMode = AutoMode.A1,
    task_id: str = "T1",
) -> dict[str, Any]:
    """在预算内迭代修复，返回完整过程记录与指标。"""
    task = Task(id=task_id, state="AUDITING", budget=budget, auto_mode=mode, spec=spec)
    g = build_graph(spec)
    issues = audit(spec)
    task.issues = issues


    order = sorted(
        range(len(issues)),
        key=lambda k: (_SEV_RANK[issues[k].severity], issues[k].fixable),
        reverse=True,
    )

    used = 0
    task.state = "FIXING"
    for k in order:
        issue = issues[k]
        if used >= budget:
            task.pending_confirmation.append({"issue": issue.id, "reason": "budget_exhausted"})
            continue
        if not issue.fixable or issue.confidence < auto_threshold:
            task.pending_confirmation.append(
                {
                    "issue": issue.id,
                    "reason": "low_confidence" if issue.confidence < auto_threshold else "not_fixable",
                    "confidence": issue.confidence,
                }
            )
            continue
        try:
            fix = propose_fix(spec, issue, g)
        except Exception as e:  # 候选生成异常：记录并跳过，不中断整个闭环
            task.pending_confirmation.append(
                {"issue": issue.id, "reason": "propose_error", "detail": f"{type(e).__name__}: {e}"}
            )
            continue
        if fix is None:
            task.pending_confirmation.append({"issue": issue.id, "reason": "no_safe_candidate"})
            continue

        used += 1
        fix.budget_used = used
        snapshot = spec.clone()
        task.state = "VERIFYING"
        # 每轮以"本轮修复前的实况"为回归基线（已解决的约束不再被豁免检查）
        baseline_now = {i.constraint_id for i in audit(spec) if i.constraint_id}
        try:
            apply_fix(spec, fix)
            if fix.rolled_back:
                pass  # apply_fix 内部已整体回滚并写明 note
            else:
                introduced = regression_check(spec, baseline_now)
                if introduced:
                    _restore(spec, snapshot)
                    fix.rolled_back = True
                    fix.note = f"回滚：引入回归 {sorted(introduced)}"
                elif not is_resolved(spec, issue.constraint_id):
                    _restore(spec, snapshot)
                    fix.rolled_back = True
                    fix.note = "回滚：目标问题未解决"
                else:
                    fix.regression_passed = True
        except Exception as e:  # 任何未预期异常都必须回滚，避免 spec 半污染/状态卡死
            _restore(spec, snapshot)
            fix.rolled_back = True
            fix.regression_passed = False
            fix.note = f"未预期异常已回滚：{type(e).__name__}: {e}"
        task.fixes.append(fix)
        task.state = "FIXING"

    remaining = [i.constraint_id for i in audit(spec) if i.constraint_id]
    task.state = "DONE" if not remaining else "STOPPED"

    return {
        "task_id": task.id,
        "state": task.state,
        "auto_mode": mode.value,
        "issues": [asdict(i) for i in task.issues],
        "fixes": [asdict(f) for f in task.fixes],
        "pending_confirmation": task.pending_confirmation,
        "budget": {"used": used, "total": budget},
        "resolved": sum(1 for f in task.fixes if f.regression_passed and not f.rolled_back),
        "remaining": remaining,
        "final_issues_total": len(remaining),
        "final_values": {pid: p.value for pid, p in spec.params.items()},
    }