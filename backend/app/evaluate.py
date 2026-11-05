"""评估指标。

基础：检出率 / 自动修复成功率 / 回归错误率 / 预算达标率
差异化：影响集 precision/recall / 冲突仲裁正确率 / 正确拒绝率 / 误修率
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .graph import affected_constraints, build_graph, impact_metrics
from .models import Spec
from .propagate import set_param
from .rules import check_all


def evaluate_run(result: dict[str, Any], truth_issue_ids: set[str]) -> dict[str, Any]:
    """基础指标（保持向后兼容）。

    - 检出率         = 发现真问题数 / 真问题总数
    - 自动修复成功率 = 验证通过的修复数 / 修复尝试数
    - 回归错误率     = 回滚的修复数 / 修复尝试数
    - 预算达标       = 是否在预算内结束
    """
    detected = {i["constraint_id"] for i in result.get("issues", []) if i.get("constraint_id")}
    detection_rate = (
        len(detected & truth_issue_ids) / len(truth_issue_ids) if truth_issue_ids else 1.0
    )

    fixes = result.get("fixes", [])
    attempted = len(fixes)
    succeeded = sum(1 for f in fixes if f["regression_passed"] and not f["rolled_back"])
    rolled = [f for f in fixes if f["rolled_back"]]
    rolled_regression = sum(1 for f in rolled if "引入回归" in (f.get("note") or ""))
    rolled_unresolved = len(rolled) - rolled_regression

    pending = result.get("pending_confirmation", [])
    exhausted = any(p.get("reason") == "budget_exhausted" for p in pending)

    return {
        "detection_rate": round(detection_rate, 4),
        "repair_success_rate": round((succeeded / attempted) if attempted else 1.0, 4),
        # 只统计"因引入回归而回滚"，与"目标未解决导致的回滚"分离
        "regression_error_rate": round((rolled_regression / attempted) if attempted else 0.0, 4),
        "unresolved_rate": round((rolled_unresolved / attempted) if attempted else 0.0, 4),
        # 预算达标 = 未因预算耗尽而中断（原实现恒为真）
        "budget_ok": (not exhausted) and result["budget"]["used"] <= result["budget"]["total"],
        "budget_exhausted": exhausted,
        "budget_used": result["budget"]["used"],
        "fixes_attempted": attempted,
        "fixes_succeeded": succeeded,
        "detected": sorted(detected),
    }


@dataclass
class Case:
    """测试用例：任意状态机改动都应先冻结无效项。"""

    name: str
    spec: Spec
    budget: int = 5
    truth_issues: set[str] = field(default_factory=set)
    change: tuple[str, float] | None = None      # (参数, 新值) 用于影响分析
    impact_base: Spec | None = None              # 影响分析基线（默认用当前 spec）
    expect_refuse: bool = False                  # 期望拒绝自动修复
    expect_values: dict[str, float] = field(default_factory=dict)  # 仲裁期望值
    negative: bool = False                       # 无问题负样本（检测误修）

    def truth_affected(self) -> set[str]:
        """影响集真值：变更后**实际新增失败**的约束集（由独立重算得到）。"""
        if self.change is None:
            return set()
        pid, new_value = self.change
        before = {i.constraint_id for i in check_all(self.spec) if i.constraint_id}
        shadow = self.spec.clone()
        set_param(shadow, pid, new_value)
        after = {i.constraint_id for i in check_all(shadow) if i.constraint_id}
        return after - before


def compute_impact(spec: Spec, changed_param: str, new_value: float) -> dict[str, Any]:
    """影响分析评估：预测集（依赖图可达）vs 真值（实际新增失败约束）。"""
    g = build_graph(spec)
    before = {i.constraint_id for i in check_all(spec) if i.constraint_id}
    shadow = spec.clone()
    set_param(shadow, changed_param, new_value)
    after = {i.constraint_id for i in check_all(shadow) if i.constraint_id}
    truth = after - before
    predicted = affected_constraints(g, [changed_param])
    metrics = impact_metrics(predicted, truth)
    return {
        "predicted": sorted(predicted),
        "truth": sorted(truth),
        "precision": metrics["precision"],
        "recall": metrics["recall"],
    }


def evaluate_case(case: Case, result: dict[str, Any], impact: dict[str, Any] | None = None) -> dict[str, Any]:
    """单例完整指标（基础 + 差异化）。"""
    out = evaluate_run(result, case.truth_issues)
    out["name"] = case.name

    if impact is not None:
        out["impact_precision"] = impact["precision"]
        out["impact_recall"] = impact["recall"]

    if case.expect_values:
        final_values = result.get("final_values", {})
        ok = sum(
            1 for pid, want in case.expect_values.items()
            if pid in final_values and abs(final_values[pid] - want) <= 0.5
        )
        out["arbitration_accuracy"] = round(ok / len(case.expect_values), 4)

    attempted = out["fixes_attempted"]
    if case.expect_refuse:
        out["refusal_correct"] = 1.0 if (attempted == 0 and result.get("pending_confirmation")) else 0.0

    if case.negative:
        out["negative_modified"] = 1.0 if attempted > 0 else 0.0

    return out


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """聚合为测试集级指标（缺失的维度自动跳过）。"""
    if not rows:
        return {}
    n = len(rows)

    def avg(key: str, where=None) -> float | None:
        vals = [r[key] for r in rows if key in r and (where(r) if where else True)]
        return round(sum(vals) / len(vals), 4) if vals else None

    attempted_rows = lambda r: r.get("fixes_attempted", 0) > 0  # noqa: E731
    skipped = sum(1 for r in rows if not attempted_rows(r))

    return {
        "n_runs": n,
        "detection_rate": avg("detection_rate"),
        # 零尝试（拒绝修复）用例不计入成功率，避免把"没修"当成"修好了"
        "repair_success_rate": avg("repair_success_rate", attempted_rows),
        "regression_error_rate": avg("regression_error_rate", attempted_rows),
        "unresolved_rate": avg("unresolved_rate", attempted_rows),
        "budget_compliance_rate": round(sum(1 for r in rows if r["budget_ok"]) / n, 4),
        "skipped_no_attempt": skipped,
        "impact_precision": avg("impact_precision"),
        "impact_recall": avg("impact_recall"),
        "arbitration_accuracy": avg("arbitration_accuracy"),
        "refusal_accuracy": avg("refusal_correct"),
        "misrepair_rate": avg("negative_modified"),
    }