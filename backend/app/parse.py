"""图纸解析层：自适应工作模式（A0/A1/A2）与置信度模型。

首版以"结构化解析"为主（人机协同）：由尺寸清单/蓝图构建 Spec，逐项给出
置信度与是否需人工确认；低置信字段进入 A2（手动）。
视觉解析（PDF/图像）为可选适配，不在核心判定路径内。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import (
    AutoMode,
    Constraint,
    Evidence,
    EvidenceStatus,
    Feature,
    IssueLayer,
    Param,
    Severity,
    Spec,
)

THRESH_HIGH = 0.85
THRESH_LOW = 0.55


def decide_mode(confidence: float, preference: str = "auto") -> AutoMode:
    """由置信度 c 与用户意愿 p 决定自动化档位。"""
    if preference == "manual":
        return AutoMode.A2
    if confidence >= THRESH_HIGH:
        return AutoMode.A0
    if confidence >= THRESH_LOW:
        return AutoMode.A1
    return AutoMode.A2


@dataclass
class ParsedField:
    id: str
    value: float
    confidence: float
    status: EvidenceStatus
    source: str
    mode: AutoMode
    needs_confirm: bool


@dataclass
class ParseResult:
    spec: Spec
    overall_mode: AutoMode
    fields: list[ParsedField] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    drawing: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_mode": self.overall_mode.value,
            "pending": self.pending,
            "notes": self.notes,
            "drawing": self.drawing,
            "fields": [
                {
                    "id": f.id,
                    "value": f.value,
                    "confidence": f.confidence,
                    "status": f.status.value,
                    "source": f.source,
                    "mode": f.mode.value,
                    "needs_confirm": f.needs_confirm,
                }
                for f in self.fields
            ],
        }


_SEV = {"low": Severity.LOW, "medium": Severity.MEDIUM, "high": Severity.HIGH}
_LAYER = {
    "geometric": IssueLayer.GEOMETRIC,
    "drawing_model": IssueLayer.DRAWING_MODEL,
    "design_intent": IssueLayer.DESIGN_INTENT,
}


def _overall(fields: list[ParsedField], pending: list[str]) -> AutoMode:
    if pending or any(f.mode == AutoMode.A2 for f in fields):
        return AutoMode.A2
    if any(f.mode == AutoMode.A1 for f in fields):
        return AutoMode.A1
    return AutoMode.A0


def parse_blueprint(bp: dict[str, Any], preference: str = "auto") -> ParseResult:
    """由结构化蓝图构建 Spec，并标注每项证据的自动化档位。"""
    spec = Spec()
    fields: list[ParsedField] = []
    pending: list[str] = []

    for item in bp.get("params", []):
        status = EvidenceStatus(item.get("status", "inferred"))
        conf = float(item.get("confidence", 0.5))
        ev = Evidence(source=item.get("source", "unknown"), status=status,
                      confidence=conf, note=item.get("note", ""))
        spec.add_param(Param(item["id"], float(item["value"]), kind="geometry", evidence=[ev]))
        mode = decide_mode(conf, preference)
        fields.append(ParsedField(item["id"], float(item["value"]), conf, status,
                                  ev.source, mode, mode != AutoMode.A0))
        if mode == AutoMode.A2:
            pending.append(item["id"])

    for item in bp.get("derived", []):
        conf = float(item.get("confidence", 0.7))
        ev = Evidence(source=item.get("source", "rule"),
                      status=EvidenceStatus.INFERRED, confidence=conf)
        spec.add_param(Param(item["id"], float(item["value"]), kind="derived",
                             depends_on=item.get("deps", []), expr=item.get("expr"),
                             evidence=[ev]))

    for item in bp.get("features", []):
        spec.add_feature(Feature(item["id"], item["kind"], params=item.get("params", []),
                                 depends_on=item.get("depends_on", [])))

    for item in bp.get("constraints", []):
        spec.add_constraint(Constraint(
            item["id"], item["kind"], params=item.get("params", []),
            features=item.get("features", []),
            tolerance=item.get("tolerance", 1e-6),
            target=item.get("target"),
            severity=_SEV.get(item.get("severity", "high"), Severity.HIGH),
            layer=_LAYER.get(item.get("layer", "geometric"), IssueLayer.GEOMETRIC),
            fixable=item.get("fixable", True),
            description=item.get("description", ""),
        ))

    # 显式覆盖：观测值与推断值冲突时以观测值覆盖（并断开派生关系）
    for item in bp.get("overrides", []):
        pid = item["id"]
        if pid not in spec.params:
            continue
        conf = float(item.get("confidence", 0.6))
        status = EvidenceStatus(item.get("status", "observed"))
        spec.params[pid].value = float(item["value"])
        spec.params[pid].kind = "geometry"
        spec.params[pid].depends_on = []
        spec.params[pid].expr = None
        spec.params[pid].evidence = [Evidence(
            source=item.get("source", "drawing:override"),
            status=status, confidence=conf, note=item.get("note", ""))]
        mode = decide_mode(conf, preference)
        # 清理同 id 的历史条目，避免 fields 重复与 pending 残留
        pending[:] = [x for x in pending if x != pid]
        fields[:] = [f for f in fields if f.id != pid]
        fields.append(ParsedField(pid, float(item["value"]), conf, status,
                                  item.get("source", "override"),
                                  mode, mode != AutoMode.A0))
        if mode == AutoMode.A2:
            pending.append(pid)

    # 统一传播一次：override 可能改变上游参数，派生参数需按依赖重算
    try:
        from .propagate import recompute_derived

        recompute_derived(spec)
    except Exception as e:  # 表达式非法等：不阻断解析，交由人工确认
        pending.append("propagate_error")
        fields.append(ParsedField("propagate_error", 0.0, 0.0, EvidenceStatus.UNKNOWN,
                                  f"{type(e).__name__}", AutoMode.A2, True))

    return ParseResult(spec=spec, overall_mode=_overall(fields, pending),
                       fields=fields, pending=pending)