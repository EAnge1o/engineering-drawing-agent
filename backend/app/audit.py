"""三层审查编排。

层次：
- 几何与工程约束（确定性规则）
- 图纸与模型一致性（首版由结构比对承担，视觉为可选）
- 设计意图与信息完整性（缺关键尺寸/公差等）
"""
from __future__ import annotations

from .models import (
    EvidenceStatus,
    Issue,
    IssueLayer,
    Severity,
    Spec,
)
from .rules import check_all


def audit_geometric(spec: Spec) -> list[Issue]:
    """几何与工程约束层（确定性）。"""
    return check_all(spec)


def audit_design_intent(spec: Spec) -> list[Issue]:
    """设计意图与完整性层：关键尺寸无有效证据时报告（不可自动修复）。"""
    issues: list[Issue] = []
    for pid, p in spec.params.items():
        if p.status == EvidenceStatus.UNKNOWN:
            issues.append(
                Issue(
                    id=f"issue::incomplete::{pid}",
                    code="missing_dimension",
                    layer=IssueLayer.DESIGN_INTENT,
                    severity=Severity.MEDIUM,
                    confidence=0.5,
                    location={"param": pid},
                    evidence=[f"关键尺寸 {pid} 无有效证据（status=unknown）"],
                    fixable=False,
                    constraint_id=None,
                )
            )
    return issues


def audit(spec: Spec, *, include_intent: bool = True) -> list[Issue]:
    """运行全部审查层，返回问题列表。"""
    issues = audit_geometric(spec)
    if include_intent:
        issues += audit_design_intent(spec)
    return issues