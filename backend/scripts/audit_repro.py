"""审查复核：对审查报告中的问题逐条做进程内实证。

运行：在 backend 目录下执行 `python scripts/audit_repro.py`
输出：每条结论 + 证据（PASS=问题存在 / NO=未能复现）
"""
from __future__ import annotations

import ast
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

from app import api as api_mod  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from app.audit import audit  # noqa: E402
from app.cad import geometry_summary  # noqa: E402
from app.demo import build_plate_spec, plate_blueprint  # noqa: E402
from app.drawing import DrawingData, RectItem, CircleItem, TextItem, infer_blueprint  # noqa: E402
from app.evidence import build_evidence, verify_evidence  # noqa: E402
from app.fix import apply_fix, propose_fix  # noqa: E402
from app.graph import build_graph  # noqa: E402
from app.models import Constraint, Param, Spec  # noqa: E402
from app.parse import parse_blueprint  # noqa: E402
from app.propagate import set_param  # noqa: E402
from app.state import run_repair_loop  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def report(rid: str, exists: bool, evidence: str) -> None:
    RESULTS.append((rid, exists, evidence))
    print(f"[{'PASS' if exists else 'NO  '}] {rid} — {evidence}")


# ---------------------------------------------------------------- H-1
def r_h1(tmp: str) -> None:
    spec = build_plate_spec(with_defect=True)
    res = run_repair_loop(spec, budget=5)
    os.makedirs(os.path.join(tmp, "out"), exist_ok=True)
    from app.cad import export_step_stl

    extra = [p for p in export_step_stl(spec, os.path.join(tmp, "out")).values() if os.path.isfile(p)]
    m = build_evidence("T-H1", res, outdir=os.path.join(tmp, "ev"), extra_files=extra, spec_snapshot={})
    v = verify_evidence(m["manifest_path"])
    bad = [c["path"] for c in v["checks"] if not c["ok"]]
    report("H-1", v["all_ok"] is False, f"all_ok={v['all_ok']} 失败项={bad}")


# ---------------------------------------------------------------- H-2
def r_h2() -> None:
    spec = build_plate_spec(with_defect=False)
    for i in (3, 4):
        for pid in (f"hole.x{i}", f"hole.y{i}"):
            spec.params.pop(pid, None)
    try:
        geometry_summary(spec)
        report("H-2", False, "2 孔 spec 未报错（未能复现）")
    except Exception as e:
        report("H-2", isinstance(e, KeyError), f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------- H-4
def r_h4() -> None:
    # a) 非法 mode（先建真实任务，避免先撞 404）
    api_mod.create_task(api_mod.CreateTaskReq(with_defect=True, task_id="T-H4A"))
    try:
        api_mod.fix_task("T-H4A", api_mod.FixReq(budget=5, mode="b2"))
        report("H-4a", False, "非法 mode 未报错")
    except Exception as e:
        kind = type(e).__name__
        report("H-4a", kind == "ValueError", f"{kind}: {e}")

    # b) 非图纸文件：走端点（含扩展名校验），应得 422 而非裸 500
    import tempfile

    class _Upload:
        filename = "a.txt"

        async def read(self):
            return b"not a drawing"

    try:
        api_mod.asyncio.run(api_mod.create_task_from_drawing(_Upload()))
        report("H-4b", True, "端点未拒绝非法文件")
    except HTTPException as e:
        report("H-4b", e.status_code not in (413, 422), f"端点返回 {e.status_code}（期望 422）")
    except Exception as e:
        report("H-4b", True, f"端点抛出未捕获异常 {type(e).__name__}: {e}")


# ---------------------------------------------------------------- M-B3
def r_mb3() -> None:
    # a) params 与 overrides 出现同一 id -> fields 重复 + pending 残留
    bp = plate_blueprint(with_defect=False)
    bp["params"].append({"id": "hole.x4", "value": 108.0, "confidence": 0.30,
                         "status": "observed", "source": "test:dup"})
    bp["overrides"] = [{"id": "hole.x4", "value": 115.0, "confidence": 0.30,
                        "status": "observed", "source": "test:override"}]
    res = parse_blueprint(bp, preference="auto")
    ids = [f.id for f in res.fields]
    report("M-B3a", ids.count("hole.x4") > 1,
           f"fields 中 hole.x4 出现 {ids.count('hole.x4')} 次（>1 表示重复记录）")

    # b) derived 未重算
    bp2 = plate_blueprint(with_defect=False)
    bp2["overrides"] = [{"id": "plate.L", "value": 90.0, "confidence": 0.9, "status": "observed"}]
    res2 = parse_blueprint(bp2, preference="auto")
    stale = res2.spec.params["hole.x2"].value
    report("M-B3b", stale != 90.0 - 15.0,
           f"override plate.L=90 后 derived hole.x2={stale}（期望 {90.0 - 15.0}）—未重算")

    # c) override 的 status：spec 侧透传、ParsedField 侧硬编码 OBSERVED
    bp3 = plate_blueprint(with_defect=False)
    bp3["overrides"] = [{"id": "hole.x4", "value": 115.0, "confidence": 0.9,
                         "status": "user-confirmed", "source": "test"}]
    res3 = parse_blueprint(bp3, preference="auto")
    spec_status = res3.spec.params["hole.x4"].evidence[0].status.value
    field_status = next(f.status.value for f in res3.fields if f.id == "hole.x4")
    report("M-B3c", spec_status == "user-confirmed" and field_status == "observed",
           f"spec status={spec_status} / fields status={field_status}（不一致）")


# ---------------------------------------------------------------- M-B4
def r_mb4() -> None:
    spec = build_plate_spec(with_defect=False)
    set_param(spec, "hole.x4", 115.0)
    issues = audit(spec)
    g = build_graph(spec)
    target = next(i for i in issues if i.constraint_id == "c_h4_inside")
    fix = propose_fix(spec, target, g)

    # 注入"expr 引用未声明依赖"的派生参数 -> 传播时抛错，模拟 apply_fix 中途失败
    spec.add_param(Param("bad.derived", 1.0, kind="derived",
                         depends_on=["margin"], expr="plate.L - margin", evidence=[]))
    before = spec.value("hole.x4")
    try:
        apply_fix(spec, fix)
        report("M-B4", False, "apply_fix 未抛错")
    except Exception as e:
        after = spec.value("hole.x4")
        polluted = after != before
        report("M-B4", polluted,
               f"{type(e).__name__} 抛出后 hole.x4={after}（修复前 {before}）—spec 已被写入且无回滚")

    # 同样场景经状态机：异常直接穿出，任务状态停在 VERIFYING
    spec2 = build_plate_spec(with_defect=True)
    spec2.add_param(Param("bad.derived", 1.0, kind="derived",
                          depends_on=["margin"], expr="plate.L - margin", evidence=[]))
    try:
        run_repair_loop(spec2, budget=5)
        report("M-B4b", False, "状态机未抛错")
    except Exception as e:
        report("M-B4b", True, f"run_repair_loop 直接抛出 {type(e).__name__}（无兜底，任务状态卡在 VERIFYING）")


# ---------------------------------------------------------------- M-B7
def r_mb7() -> None:
    # a) budget_ok 恒真：预算不足导致未修完，budget_ok 仍为 True
    spec = build_plate_spec(with_defect=False)
    set_param(spec, "margin", 5.0)  # 4 条约束失败
    res = run_repair_loop(spec, budget=1)
    from app.evaluate import evaluate_run

    m = evaluate_run(res, {f"c_h{k}_inside" for k in range(1, 5)})
    report("M-B7a", m["budget_ok"] is True and len(res["remaining"]) > 0,
           f"budget_used={m['budget_used']}, remaining={len(res['remaining'])} 但 budget_ok={m['budget_ok']}")

    # b) 零尝试记为"修复成功"
    spec2 = build_plate_spec(with_defect=True)
    spec2.params["hole.x4"].evidence[0].confidence = 0.30
    res2 = run_repair_loop(spec2, budget=5)
    m2 = evaluate_run(res2, {"c_h4_inside"})
    # 单例口径仍为 1.0，但聚合时应被跳过；这里检验聚合行为
    from app.evaluate import aggregate

    agg = aggregate([m2])
    fixed = (agg.get("skipped_no_attempt") == 1 and agg.get("repair_success_rate") is None)
    report("M-B7b", not fixed,
           f"aggregate skipped={agg.get('skipped_no_attempt')} "
           f"repair_success_rate={agg.get('repair_success_rate')}（None=零尝试已跳过）")


# ---------------------------------------------------------------- M-B11
def r_mb11() -> None:
    import app.store as store

    rel = not os.path.isabs(api_mod._DB) and not os.path.isabs(store.DEFAULT_DB)
    report("M-B11", rel, f"DB={api_mod._DB!r} / DEFAULT_DB={store.DEFAULT_DB!r} 均为相对路径（随 CWD 漂移）")


# ---------------------------------------------------------------- M-B12
def r_mb12() -> None:
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "llm.py")
    src = open(p, encoding="utf-8").read()
    has_nested = "{c['param']}" in src or "{c['old']}" in src
    # 用 3.10 语法特性版本解析（PEP 701 嵌套引号在旧版本不可解析，3.13 解释器仍可读）
    parse_ok_310 = True
    try:
        ast.parse(src, feature_version=(3, 10))
    except SyntaxError as e:
        parse_ok_310 = False
        _ = e
    report("M-B12", has_nested, f"存在同引号嵌套 f-string（PEP 701）={has_nested}；"
                                 f"ast(feature_version=3.10) 可解析={parse_ok_310}"
                                 f"（注：解析器为 3.13，无法完全代表 3.10 运行时）")


# ---------------------------------------------------------------- M-B5
def r_mb5() -> None:
    dd = DrawingData(source="portrait.pdf", text_backend="pdf")
    dd.rects = [RectItem(0, 0, 100, 200)]          # 竖版外框：宽 100 / 高 200
    dd.texts = [TextItem("200", 0, 0, 0, 0, 0.9), TextItem("100", 0, 0, 0, 0, 0.9),
                TextItem("4x D10", 0, 0, 0, 0, 0.9)]
    dd.circles = [CircleItem(50, 150, 3), CircleItem(50, 50, 3)]
    bp = infer_blueprint(dd)
    holes = dict((p["id"], p["value"]) for p in bp["params"] if p["id"].startswith("hole."))
    h1 = holes.get("hole.x1")
    report("M-B5", h1 is not None and h1 > 60.0,
           f"竖版 rect(100x200) L=200 时 scale={dd.scale_px_per_mm}（应为 1.0），"
           f"孔 x1={h1}（真实坐标应约 50，被放大 {200/100:.0f} 倍）")


def r_mb10() -> None:
    api_mod.create_task(api_mod.CreateTaskReq(with_defect=True, task_id="T-DUP"))
    v1 = api_mod._TASKS["T-DUP"]["spec"].params["hole.x4"].value
    try:
        api_mod.create_task(api_mod.CreateTaskReq(with_defect=False, task_id="T-DUP"))
        v2 = api_mod._TASKS["T-DUP"]["spec"].params["hole.x4"].value
        report("M-B10", True, f"同 task_id 二次创建未报错并静默覆盖（hole.x4: {v1} -> {v2}）")
    except Exception as e:
        report("M-B10", False, f"已做查重保护：{type(e).__name__}")


def r_mb2() -> None:
    """回归基线：确认状态机改为"每轮以当前失败集为基线"。"""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "state.py")
    src = open(p, encoding="utf-8").read()
    fixed = "baseline_now" in src and "baseline_ids = {" not in src
    report("M-B2", not fixed,
           "已修复：每轮以 baseline_now（当前失败集）为回归基线" if fixed else "仍使用循环外固化基线")


def r_frontend() -> None:
    """前端 5 项中危 + H-3 的修复确认（静态断言关键实现标记）。"""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    fe = os.path.join(root, "frontend", "src")

    def read(rel: str) -> str:
        with open(os.path.join(fe, rel), encoding="utf-8") as fh:
            return fh.read()

    store = read("store.js")
    app = read("app.js")
    viewer = read("components/ViewerPanel.js")

    checks = [
        ("H-3", "forceContextLoss" in viewer and "disposeObject" in viewer, "WebGL 全量释放"),
        ("H-3b", "[geometry, highlight, autoRotate, wire, dims]" not in viewer,
         "开关不再重建渲染器（拆分 effect）"),
        ("M-F1", 'busy === "fix"' in store and "if (s.busy) return" in app, "忙碌守卫（含快捷键）"),
        ("M-F2", "seqRef" in store, "解析请求序号防竞态"),
        ("M-F3", "holeFlagFrom" in store and "holeFlagFrom" in app, "高亮 ID 域映射"),
        ("M-F4", "Math.round(Number(e.target.value)" in app, "预算取整钳制"),
        ("M-F5", "ResizeObserver" in viewer and "el.clientHeight || h0" in viewer, "实时高度 + ResizeObserver"),
        ("L-F1", "fromFixes" in read("components/DiffCompare.js"), "对比回退不再全 0"),
        ("L-F2", "remainingIds" in read("components/IssueList.js"), "已解决标识"),
        ("L-F4", "ALLOWED" in read("components/DropZone.js"), "拖放类型校验"),
        ("L-F5", "useMemo" in read("components/Toast.js"), "Toast 稳定引用"),
        ("L-F6", "shownRef" in read("components/Stat.js"), "动画起点用当前显示值"),
    ]
    for cid, ok, desc in checks:
        report(cid, not ok, f"{'已修复' if ok else '未修复'}：{desc}")


def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        r_h1(tmp)
    r_h2()
    r_h4()
    r_mb3()
    r_mb4()
    r_mb2()
    r_mb7()
    r_mb10()
    r_mb11()
    r_mb12()
    r_mb5()
    print()
    r_frontend()

    bad = [r for r in RESULTS if not r[1]]
    print(f"\n汇总：{len(RESULTS) - len(bad)}/{len(RESULTS)} 条问题已复现为真")
    if bad:
        print("未复现：" + ", ".join(r[0] for r in bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())