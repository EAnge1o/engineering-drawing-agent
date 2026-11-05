"""演示零件：带多个安装孔的矩形机械板。

规格：120 × 80 × 6 mm 板，4 × φ6.5 安装孔，R5 过渡圆角。
提供 build_plate_spec(with_defect=...) 以注入/不注入已知缺陷（用于演示与评估）。
"""
from __future__ import annotations

from .models import (
    Constraint,
    Evidence,
    EvidenceStatus,
    Feature,
    IssueLayer,
    Param,
    Severity,
    Spec,
)

# 图纸标注（"图纸真值"）
TRUE_L = 120.0
TRUE_W = 80.0
TRUE_T = 6.0
TRUE_FILLET = 5.0
TRUE_DIAM = 6.5
TRUE_MARGIN = 15.0


def _ev(source: str, conf: float, status: EvidenceStatus = EvidenceStatus.OBSERVED) -> Evidence:
    return Evidence(source=source, status=status, confidence=conf)


def build_plate_spec(with_defect: bool = False) -> Spec:
    spec = Spec()

    # ---- 参数 ----
    spec.add_param(Param("plate.L", TRUE_L, evidence=[_ev("drawing:overall", 0.95)]))
    spec.add_param(Param("plate.W", TRUE_W, evidence=[_ev("drawing:overall", 0.95)]))
    spec.add_param(Param("plate.T", TRUE_T, evidence=[_ev("drawing:side_view", 0.9)]))
    spec.add_param(Param("fillet.r", TRUE_FILLET, evidence=[_ev("drawing:note_r5", 0.8)]))
    spec.add_param(Param("hole.d", TRUE_DIAM, evidence=[_ev("drawing:hole_callout", 0.92)]))
    spec.add_param(Param("margin", TRUE_MARGIN, evidence=[_ev("drawing:chain_dim", 0.88)]))

    # 孔位（派生：x2/x4 = L - margin，y2/y3 = W - margin）
    def _derived(pid: str, expr: str, deps: list[str], value: float, src: str) -> Param:
        return Param(pid, value, kind="derived", depends_on=deps, expr=expr,
                     evidence=[_ev(src, 0.7, EvidenceStatus.INFERRED)])

    spec.add_param(_derived("hole.x1", "margin", ["margin"], TRUE_MARGIN, "rule:x1=margin"))
    spec.add_param(_derived("hole.y1", "margin", ["margin"], TRUE_MARGIN, "rule:y1=margin"))
    spec.add_param(_derived("hole.x2", "plate.L - margin", ["plate.L", "margin"],
                            TRUE_L - TRUE_MARGIN, "rule:x2=L-margin"))
    spec.add_param(_derived("hole.y2", "margin", ["margin"], TRUE_MARGIN, "rule:y2=margin"))
    spec.add_param(_derived("hole.x3", "margin", ["margin"], TRUE_MARGIN, "rule:x3=margin"))
    spec.add_param(_derived("hole.y3", "plate.W - margin", ["plate.W", "margin"],
                            TRUE_W - TRUE_MARGIN, "rule:y3=W-margin"))
    spec.add_param(_derived("hole.x4", "plate.L - margin", ["plate.L", "margin"],
                            TRUE_L - TRUE_MARGIN, "rule:x4=L-margin"))
    spec.add_param(_derived("hole.y4", "plate.W - margin", ["plate.W", "margin"],
                            TRUE_W - TRUE_MARGIN, "rule:y4=W-margin"))

    # ---- 特征 ----
    spec.add_feature(Feature("plate_body", "extrude", params=["plate.L", "plate.W", "plate.T"]))
    for i in range(1, 5):
        spec.add_feature(Feature(f"hole_h{i}", "hole", params=[f"hole.x{i}", f"hole.y{i}", "hole.d"],
                                 depends_on=["plate_body"]))
    spec.add_feature(Feature("hole_pattern", "hole_pattern", params=["hole.d"],
                             depends_on=[f"hole_h{i}" for i in range(1, 5)]))
    spec.add_feature(Feature("fillet_01", "fillet", params=["fillet.r"], depends_on=["plate_body"]))

    # ---- 约束 ----
    spec.add_constraint(Constraint("c_L_pos", "geom_positive", params=["plate.L"]))
    spec.add_constraint(Constraint("c_W_pos", "geom_positive", params=["plate.W"]))
    spec.add_constraint(Constraint("c_T_pos", "geom_positive", params=["plate.T"]))
    spec.add_constraint(Constraint("c_fillet_max", "max_value", params=["fillet.r"], target=10.0,
                                   severity=Severity.MEDIUM))
    spec.add_constraint(Constraint("c_diam_eq", "equality", params=["hole.d"], target=TRUE_DIAM,
                                   tolerance=0.01, severity=Severity.MEDIUM))
    # 孔必须完全位于板内，且距边不小于最小边距（12mm）
    for i in range(1, 5):
        spec.add_constraint(Constraint(
            f"c_h{i}_inside", "hole_inside",
            params=[f"hole.x{i}", f"hole.y{i}", "plate.L", "plate.W"], target=12.0,
            severity=Severity.HIGH,
        ))
    # 孔间距不小于 20mm
    spec.add_constraint(Constraint("c_sp_h1h2", "spacing_min",
                                   params=["hole.x1", "hole.y1", "hole.x2", "hole.y2"], target=20.0))
    spec.add_constraint(Constraint("c_sp_h1h3", "spacing_min",
                                   params=["hole.x1", "hole.y1", "hole.x3", "hole.y3"], target=20.0))
    spec.add_constraint(Constraint("c_sp_h2h4", "spacing_min",
                                   params=["hole.x2", "hole.y2", "hole.x4", "hole.y4"], target=20.0))

    if with_defect:
        # 缺陷：右上孔 x 标注为 115（越界，且边距 5 < 12）
        spec.params["hole.x4"].value = 115.0
        spec.params["hole.x4"].kind = "geometry"
        spec.params["hole.x4"].depends_on = []
        spec.params["hole.x4"].expr = None
        spec.params["hole.x4"].evidence = [
            Evidence(source="drawing:dim_115", status=EvidenceStatus.OBSERVED, confidence=0.6,
                     note="与'边距=15'尺寸链不一致")
        ]

    return spec

PLATE_BLUEPRINT: dict = {
    "params": [
        {"id": "plate.L", "value": TRUE_L, "confidence": 0.95, "status": "observed", "source": "drawing:overall"},
        {"id": "plate.W", "value": TRUE_W, "confidence": 0.95, "status": "observed", "source": "drawing:overall"},
        {"id": "plate.T", "value": TRUE_T, "confidence": 0.90, "status": "observed", "source": "drawing:side_view"},
        {"id": "fillet.r", "value": TRUE_FILLET, "confidence": 0.80, "status": "observed", "source": "drawing:note_r5"},
        {"id": "hole.d", "value": TRUE_DIAM, "confidence": 0.92, "status": "observed", "source": "drawing:hole_callout"},
        {"id": "margin", "value": TRUE_MARGIN, "confidence": 0.88, "status": "observed", "source": "drawing:chain_dim"},
    ],
    "derived": [
        {"id": "hole.x1", "expr": "margin", "deps": ["margin"], "value": TRUE_MARGIN, "source": "rule:x1=margin"},
        {"id": "hole.y1", "expr": "margin", "deps": ["margin"], "value": TRUE_MARGIN, "source": "rule:y1=margin"},
        {"id": "hole.x2", "expr": "plate.L - margin", "deps": ["plate.L", "margin"],
         "value": TRUE_L - TRUE_MARGIN, "source": "rule:x2=L-margin"},
        {"id": "hole.y2", "expr": "margin", "deps": ["margin"], "value": TRUE_MARGIN, "source": "rule:y2=margin"},
        {"id": "hole.x3", "expr": "margin", "deps": ["margin"], "value": TRUE_MARGIN, "source": "rule:x3=margin"},
        {"id": "hole.y3", "expr": "plate.W - margin", "deps": ["plate.W", "margin"],
         "value": TRUE_W - TRUE_MARGIN, "source": "rule:y3=W-margin"},
        {"id": "hole.x4", "expr": "plate.L - margin", "deps": ["plate.L", "margin"],
         "value": TRUE_L - TRUE_MARGIN, "source": "rule:x4=L-margin"},
        {"id": "hole.y4", "expr": "plate.W - margin", "deps": ["plate.W", "margin"],
         "value": TRUE_W - TRUE_MARGIN, "source": "rule:y4=W-margin"},
    ],
    "features": [
        {"id": "plate_body", "kind": "extrude", "params": ["plate.L", "plate.W", "plate.T"]},
        *[{"id": f"hole_h{i}", "kind": "hole", "params": [f"hole.x{i}", f"hole.y{i}", "hole.d"],
           "depends_on": ["plate_body"]} for i in range(1, 5)],
        {"id": "hole_pattern", "kind": "hole_pattern", "params": ["hole.d"],
         "depends_on": [f"hole_h{i}" for i in range(1, 5)]},
        {"id": "fillet_01", "kind": "fillet", "params": ["fillet.r"], "depends_on": ["plate_body"]},
    ],
    "constraints": [
        {"id": "c_L_pos", "kind": "geom_positive", "params": ["plate.L"]},
        {"id": "c_W_pos", "kind": "geom_positive", "params": ["plate.W"]},
        {"id": "c_T_pos", "kind": "geom_positive", "params": ["plate.T"]},
        {"id": "c_fillet_max", "kind": "max_value", "params": ["fillet.r"], "target": 10.0, "severity": "medium"},
        {"id": "c_diam_eq", "kind": "equality", "params": ["hole.d"], "target": TRUE_DIAM,
         "tolerance": 0.01, "severity": "medium"},
        *[{"id": f"c_h{i}_inside", "kind": "hole_inside",
           "params": [f"hole.x{i}", f"hole.y{i}", "plate.L", "plate.W"],
           "target": 12.0, "severity": "high"} for i in range(1, 5)],
        {"id": "c_sp_h1h2", "kind": "spacing_min", "params": ["hole.x1", "hole.y1", "hole.x2", "hole.y2"], "target": 20.0},
        {"id": "c_sp_h1h3", "kind": "spacing_min", "params": ["hole.x1", "hole.y1", "hole.x3", "hole.y3"], "target": 20.0},
        {"id": "c_sp_h2h4", "kind": "spacing_min", "params": ["hole.x2", "hole.y2", "hole.x4", "hole.y4"], "target": 20.0},
    ],
}


def plate_blueprint(with_defect: bool = False) -> dict:
    """返回矩形板蓝图的副本；with_defect=True 时注入孔位缺陷。"""
    import copy as _copy

    bp = _copy.deepcopy(PLATE_BLUEPRINT)
    if with_defect:
        bp["overrides"] = [{
            "id": "hole.x4",
            "value": 115.0,
            "confidence": 0.60,
            "status": "observed",
            "source": "drawing:dim_115",
            "note": "与'边距=15'尺寸链不一致",
        }]
    return bp