"""核心数据模型。

为「参数依赖图 + 确定性审查 + 局部修复 + 回归验证」提供无外部依赖、可序列化的
中间表示。几何内核（CadQuery）为可选适配层，本模块不依赖它。
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class EvidenceStatus(str, Enum):
    """证据状态：区分观测值 / 推断值 / 用户确认值 / 未知。"""

    OBSERVED = "observed"
    INFERRED = "inferred"
    USER_CONFIRMED = "user-confirmed"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AutoMode(str, Enum):
    """自适应自动化档位（由置信度 c 与用户意愿 p 共同决定）。"""

    A0 = "A0"  # 全自动
    A1 = "A1"  # 辅助：高风险项请求确认
    A2 = "A2"  # 手动


class IssueLayer(str, Enum):
    GEOMETRIC = "geometric"            # 几何与工程约束
    DRAWING_MODEL = "drawing_model"    # 图纸与模型一致性
    DESIGN_INTENT = "design_intent"    # 设计意图与信息完整性


@dataclass
class Evidence:
    source: str
    status: EvidenceStatus = EvidenceStatus.INFERRED
    confidence: float = 0.5
    note: str = ""


@dataclass
class Param:
    """一个带单位与证据链的数值参数。"""

    id: str
    value: float
    unit: str = "mm"
    kind: str = "geometry"            # geometry | derived
    depends_on: list[str] = field(default_factory=list)  # 派生参数的上游
    expr: Optional[str] = None        # 派生参数的算术表达式（变量=depends_on 中的 id）
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        if not self.evidence:
            return 0.5
        return max(e.confidence for e in self.evidence)

    @property
    def status(self) -> EvidenceStatus:
        if any(e.status == EvidenceStatus.USER_CONFIRMED for e in self.evidence):
            return EvidenceStatus.USER_CONFIRMED
        if not self.evidence:
            return EvidenceStatus.UNKNOWN
        return max(self.evidence, key=lambda e: e.confidence).status


@dataclass
class Feature:
    """参数化特征（拉伸/孔/孔阵列/倒角/圆角）。"""

    id: str
    kind: str                          # extrude|hole|hole_pattern|fillet|chamfer
    params: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class Constraint:
    """一条可确定性判定的工程约束。"""

    id: str
    kind: str                          # geom_positive|equality|max_value|
                                       # max_value_ratio|hole_inside|spacing_min
    params: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    tolerance: float = 1e-6
    target: Optional[float] = None     # 期望值/阈值/最小间距/最小边距
    severity: Severity = Severity.HIGH
    layer: IssueLayer = IssueLayer.GEOMETRIC
    fixable: bool = True
    description: str = ""


@dataclass
class Issue:
    """一条审查发现的问题（统一记录位置/证据/严重度/置信度）。"""

    id: str
    code: str
    layer: IssueLayer
    severity: Severity
    confidence: float
    location: dict[str, Any]
    evidence: list[str]
    fixable: bool
    constraint_id: Optional[str] = None
    fix_hint: Optional[dict[str, Any]] = None   # 建议的修复方向


@dataclass
class FixChange:
    param: str
    old: float
    new: float


@dataclass
class Fix:
    """一次修复尝试（含影响面与回归结果，可回滚）。"""

    fix_id: str
    issue_id: str
    changes: list[FixChange]
    affected_features: list[str] = field(default_factory=list)
    affected_constraints: list[str] = field(default_factory=list)
    regression_passed: bool = False
    rolled_back: bool = False
    budget_used: int = 0
    note: str = ""


@dataclass
class Spec:
    """零件规格：参数 + 特征 + 约束。"""

    params: dict[str, Param] = field(default_factory=dict)
    features: dict[str, Feature] = field(default_factory=dict)
    constraints: dict[str, Constraint] = field(default_factory=dict)

    def add_param(self, p: Param) -> Param:
        self.params[p.id] = p
        return p

    def add_feature(self, f: Feature) -> Feature:
        self.features[f.id] = f
        return f

    def add_constraint(self, c: Constraint) -> Constraint:
        self.constraints[c.id] = c
        return c

    def value(self, pid: str) -> float:
        return self.params[pid].value

    def set_value(self, pid: str, value: float) -> None:
        self.params[pid].value = value

    def clone(self) -> "Spec":
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Spec":
        """由 to_dict() 的输出重建 Spec（用于持久化回灌）。"""
        spec = cls()
        for pid, pd in (data.get("params") or {}).items():
            evs = [
                Evidence(
                    source=e.get("source", "restored"),
                    status=EvidenceStatus(e.get("status", "observed")),
                    confidence=float(e.get("confidence", 0.5)),
                    note=e.get("note", ""),
                )
                for e in (pd.get("evidence") or [])
            ]
            spec.params[pid] = Param(
                id=pd["id"], value=float(pd["value"]), unit=pd.get("unit", "mm"),
                kind=pd.get("kind", "geometry"),
                depends_on=list(pd.get("depends_on") or []),
                expr=pd.get("expr"), evidence=evs,
            )
        for fid, fd in (data.get("features") or {}).items():
            spec.features[fid] = Feature(
                id=fd["id"], kind=fd["kind"],
                params=list(fd.get("params") or []),
                depends_on=list(fd.get("depends_on") or []),
            )
        for cid, cd in (data.get("constraints") or {}).items():
            spec.constraints[cid] = Constraint(
                id=cd["id"], kind=cd["kind"],
                params=list(cd.get("params") or []),
                features=list(cd.get("features") or []),
                tolerance=cd.get("tolerance", 1e-6), target=cd.get("target"),
                severity=Severity(cd.get("severity", "high")),
                layer=IssueLayer(cd.get("layer", "geometric")),
                fixable=cd.get("fixable", True),
                description=cd.get("description", ""),
            )
        return spec


@dataclass
class Task:
    id: str
    state: str = "IDLE"
    auto_mode: AutoMode = AutoMode.A1
    budget: int = 5
    spec: Optional[Spec] = None
    issues: list[Issue] = field(default_factory=list)
    fixes: list[Fix] = field(default_factory=list)
    pending_confirmation: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)