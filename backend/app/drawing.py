"""真实图纸解析：矢量 PDF 优先，位图走 OpenCV + OCR 兜底。

流程：加载图纸 → 提取文字（PDF 文字层 / OCR）→ 检测轮廓（矩形外框 + 圆形孔）
→ 推断蓝图（尺寸、比例、孔位）→ 交给 parse.parse_blueprint 生成 Spec。

与人机协同设计一致：任何无法自动确定的量都带低置信度并交由用户确认。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

try:  # PyMuPDF（新版本包名 pymupdf，旧名 fitz）
    import pymupdf as fitz
except Exception:  # pragma: no cover
    try:
        import fitz
    except Exception:
        fitz = None

try:  # OpenCV
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

_NUM = re.compile(r"\d+(?:\.\d+)?")
_DIA = re.compile(r"[DØΦφ]")


@dataclass
class TextItem:
    text: str
    x: float
    y: float
    w: float = 0.0
    h: float = 0.0
    confidence: float = 0.9


@dataclass
class RectItem:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return abs(self.x1 - self.x0)

    @property
    def h(self) -> float:
        return abs(self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.w * self.h


@dataclass
class CircleItem:
    cx: float
    cy: float
    r: float


@dataclass
class DrawingData:
    source: str
    texts: list[TextItem] = field(default_factory=list)
    rects: list[RectItem] = field(default_factory=list)
    circles: list[CircleItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    text_backend: str = "none"
    scale_px_per_mm: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "text_backend": self.text_backend,
            "scale_px_per_mm": round(self.scale_px_per_mm, 4) if self.scale_px_per_mm else None,
            "texts": [t.text for t in self.texts],
            "rects": [[round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)] for r in self.rects],
            "circles": [[round(c.cx, 1), round(c.cy, 1), round(c.r, 1)] for c in self.circles],
            "notes": self.notes,
        }


# --------------------------------------------------------------------------- #
# 文字提取
# --------------------------------------------------------------------------- #
def _text_from_pdf(path: str, zoom: float) -> list[TextItem]:
    if fitz is None:
        return []
    doc = fitz.open(path)
    page = doc[0]
    items: list[TextItem] = []
    for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        items.append(TextItem(word, x0 * zoom, y0 * zoom,
                              (x1 - x0) * zoom, (y1 - y0) * zoom, 0.9))
    doc.close()
    return items


def _text_from_raster(img: np.ndarray) -> tuple[list[TextItem], str]:
    """位图文字：pytesseract → 系统 tesseract → 无（交由人工录入）。"""
    try:
        import pytesseract  # type: ignore

        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        items: list[TextItem] = []
        for i, txt in enumerate(data["text"]):
            if txt.strip():
                items.append(TextItem(txt.strip(), float(data["left"][i]), float(data["top"][i]),
                                      float(data["width"][i]), float(data["height"][i]),
                                      min(0.95, max(0.3, float(data["conf"][i]) / 100))))
        return items, "pytesseract"
    except Exception:
        pass

    exe = shutil.which("tesseract")
    if exe:
        try:
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                p = os.path.join(tmp, "img.png")
                cv2.imwrite(p, img)
                out = os.path.join(tmp, "out")
                subprocess.run([exe, p, out, "--psm", "11"],
                               capture_output=True, timeout=30, check=False)
                items: list[TextItem] = []
                txt_path = out + ".txt"
                if os.path.exists(txt_path):
                    for line in open(txt_path, encoding="utf-8", errors="ignore"):
                        for tok in line.split():
                            items.append(TextItem(tok, 0, 0, 0, 0, 0.6))
                return items, "tesseract-cli"
        except Exception:
            pass

    return [], "manual"


# --------------------------------------------------------------------------- #
# 图形检测
# --------------------------------------------------------------------------- #
def _dedupe(circles: list[CircleItem], min_dist: float = 14.0) -> list[CircleItem]:
    out: list[CircleItem] = []
    for c in sorted(circles, key=lambda c: -c.r):
        if all((c.cx - o.cx) ** 2 + (c.cy - o.cy) ** 2 > min_dist ** 2 for o in out):
            out.append(c)
    return out


def _cluster(circles: list[CircleItem], dist: float = 45.0) -> list[CircleItem]:
    """按邻近度聚类，每类取半径最大的圆作为代表（抑制 Hough 噪声）。"""
    reps: list[CircleItem] = []
    for c in sorted(circles, key=lambda c: -c.r):
        if not any((c.cx - o.cx) ** 2 + (c.cy - o.cy) ** 2 <= dist ** 2 for o in reps):
            reps.append(c)
    return reps


def _detect_shapes(img: np.ndarray) -> tuple[list[RectItem], list[CircleItem]]:
    if cv2 is None:
        return [], []
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    blur = cv2.GaussianBlur(gray, (3, 3), 0)

    circles: list[CircleItem] = []
    hc = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=25,
                          param1=120, param2=18, minRadius=4, maxRadius=80)
    if hc is not None:
        for x, y, r in np.round(hc[0]).astype(int):
            circles.append(CircleItem(float(x), float(y), float(r)))

    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects: list[RectItem] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w > 40 and h > 40:
            rects.append(RectItem(float(x), float(y), float(x + w), float(y + h)))
    return rects, _dedupe(circles)


# --------------------------------------------------------------------------- #
# 载入
# --------------------------------------------------------------------------- #
def _load_raster(path: str, dpi: int = 150) -> tuple[np.ndarray, float]:
    """返回 (BGR 图像, zoom)。PDF 用 zoom = dpi/72 渲染；位图 zoom = 1。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        if fitz is None:
            raise RuntimeError("解析 PDF 需要 PyMuPDF（pip install pymupdf）")
        doc = fitz.open(path)
        page = doc[0]
        pm = page.get_pixmap(dpi=dpi)
        img = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, pm.n)
        img = img[:, :, :3][:, :, ::-1].copy()  # RGB -> BGR
        doc.close()
        return img, dpi / 72.0
    if cv2 is None:
        raise RuntimeError("解析位图需要 OpenCV（pip install opencv-python）")
    img = cv2.imread(path)
    if img is None:
        raise RuntimeError(f"无法读取图像: {path}")
    return img, 1.0


def extract_drawing(path: str, dpi: int = 150) -> DrawingData:
    """提取图纸的文字与图形（统一坐标系）。"""
    img, zoom = _load_raster(path, dpi)
    dd = DrawingData(source=os.path.basename(path))

    if os.path.splitext(path)[1].lower() == ".pdf":
        dd.texts = _text_from_pdf(path, zoom)
        dd.text_backend = "pdf"
    else:
        dd.texts, dd.text_backend = _text_from_raster(img)
    if dd.text_backend == "manual":
        dd.notes.append("未检测到 OCR 能力：位图文字需人工录入（人机协同）")

    dd.rects, dd.circles = _detect_shapes(img)
    if not dd.rects:
        dd.notes.append("未检测到零件外轮廓")
    return dd


# --------------------------------------------------------------------------- #
# 推断蓝图
# --------------------------------------------------------------------------- #
def _numbers(texts: list[TextItem]) -> list[tuple[float, str, float]]:
    out: list[tuple[float, str, float]] = []
    for t in texts:
        for m in _NUM.findall(t.text):
            out.append((float(m), t.text, t.confidence))
    return out


def _diameter(texts: list[TextItem]) -> tuple[float | None, float]:
    for t in texts:
        if _DIA.search(t.text):
            nums = _NUM.findall(t.text)
            if nums:
                return float(nums[-1]), t.confidence
    for t in texts:
        for n in _NUM.findall(t.text):
            if "." in n:
                return float(n), t.confidence * 0.7
    return None, 0.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


_VISION_PROMPT = """你是资深机械制图工程师。请阅读这张二维零件工程图，提取用于参数化建模的关键尺寸。

只输出一个 JSON 对象，不要输出解释、Markdown 或代码围栏。格式：
{
  "unit": "mm",
  "plate": {
    "L": {"value": 120.0, "confidence": 0.92},
    "W": {"value": 80.0, "confidence": 0.92},
    "T": {"value": 6.0, "confidence": 0.5}
  },
  "fillet_r": {"value": 5.0, "confidence": 0.6},
  "hole": {
    "d": {"value": 6.5, "confidence": 0.85},
    "centers": [{"x": 15.0, "y": 15.0, "confidence": 0.8}]
  },
  "margin": {"value": 15.0, "confidence": 0.6},
  "notes": ["图中未标注板厚，T 为推测值"]
}

规则：
1. L / W / T 单位为 mm，分别对应零件长度（X 向）、宽度（Y 向）、厚度。
2. 孔标注若为直径（φ、D、Ø），hole.d 直接填直径数值，不要填半径。
3. 孔中心坐标以零件左下角为原点，x 向右、y 向上，单位 mm。
4. 图纸未标注或看不清的项：value 填 null、confidence 填 0，并在 notes 说明原因。
5. 不要臆测未标注的厚度、圆角与孔位；没有依据就填 null。
6. confidence 是你对该数值的把握（0~1），请如实给出，不要一律填高。
"""


def _num(value: Any) -> float | None:
    """安全转 float；过滤 None / bool / NaN / Inf。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _pair(item: Any) -> tuple[float, float] | None:
    """把 {"value":..,"confidence":..} 或裸数字归一为 (值, 置信度)。"""
    if item is None:
        return None
    if isinstance(item, (int, float)) and not isinstance(item, bool):
        v = _num(item)
        return (v, 0.6) if v is not None else None
    if isinstance(item, dict):
        v = _num(item.get("value"))
        if v is None:
            return None
        c = _num(item.get("confidence"))
        return (v, 0.6 if c is None else max(0.0, min(1.0, c)))
    return None


def _normalize_vision(data: dict[str, Any]) -> dict[str, Any]:
    """把模型输出归一为内部结构；不合法项直接丢弃（宁缺毋滥）。"""
    params: dict[str, dict[str, Any]] = {}
    plate = data.get("plate") if isinstance(data.get("plate"), dict) else {}

    for pid, item in (
        ("plate.L", plate.get("L", data.get("plate.L"))),
        ("plate.W", plate.get("W", data.get("plate.W"))),
        ("plate.T", plate.get("T", data.get("plate.T"))),
        ("fillet.r", data.get("fillet_r", data.get("fillet.r"))),
        ("margin", data.get("margin")),
    ):
        pair = _pair(item)
        if pair is not None and pair[0] > 0:
            params[pid] = {"value": round(pair[0], 4), "confidence": round(pair[1], 3)}

    hole = data.get("hole") if isinstance(data.get("hole"), dict) else {}
    hd = _pair(hole.get("d", data.get("hole.d")))
    if hd is not None and hd[0] > 0:
        params["hole.d"] = {"value": round(hd[0], 4), "confidence": round(hd[1], 3)}

    holes: list[dict[str, float]] = []
    for c in (hole.get("centers") or [])[:4]:
        if not isinstance(c, dict):
            continue
        x, y = _num(c.get("x")), _num(c.get("y"))
        if x is None or y is None or x < 0 or y < 0:
            continue
        conf = _num(c.get("confidence"))
        holes.append({
            "x": round(x, 2),
            "y": round(y, 2),
            "confidence": round(0.75 if conf is None else max(0.0, min(1.0, conf)), 3),
        })

    notes = [
        str(n)[:200]
        for n in (data.get("notes") or [])
        if isinstance(n, (str, int, float))
    ][:8]

    if not params and not holes:
        return {}
    return {"params": params, "holes": holes, "notes": notes, "raw": data}


# 多模态熔断：连续失败 N 次后暂停调用一段时间，避免演示中因凭据失效/网络挂起
# 导致每次解析都阻塞到超时。
_VISION_GUARD_LOCK = threading.Lock()
_VISION_FAILS = 0
_VISION_COOLDOWN_UNTIL = 0.0
VISION_FAIL_THRESHOLD = 3
VISION_COOLDOWN_S = 60.0


def _vision_guard_blocked() -> bool:
    with _VISION_GUARD_LOCK:
        return time.time() < _VISION_COOLDOWN_UNTIL


def _vision_guard_record(ok: bool) -> None:
    """记录一次多模态调用结果，维护熔断状态。"""
    global _VISION_FAILS, _VISION_COOLDOWN_UNTIL
    with _VISION_GUARD_LOCK:
        if ok:
            _VISION_FAILS = 0
            return
        _VISION_FAILS += 1
        if _VISION_FAILS >= VISION_FAIL_THRESHOLD:
            _VISION_COOLDOWN_UNTIL = time.time() + VISION_COOLDOWN_S
            _VISION_FAILS = 0


def vision_candidates(path: str) -> dict[str, Any] | None:
    """用 MaaS 多模态模型提取图纸候选尺寸。

    返回值为"候选证据"：调用方必须将其标记为 inferred 并交由确定性内核复核。
    未配置模型、图片编码失败或模型输出不合法时返回 None（不影响主流程）。
    连续失败达到阈值后进入冷却期，期间直接跳过，避免拖慢每次解析。
    """
    from .llm import complete_vision, extract_json, vision_available

    if not vision_available():
        return None
    if _vision_guard_blocked():
        return None

    try:
        text = complete_vision(
            path, _VISION_PROMPT,
            system="你是严谨的机械制图专家，只依据图纸可见标注作答，只输出 JSON。",
        )
    except Exception:
        _vision_guard_record(False)
        return None

    data = extract_json(text) if text else None
    if not isinstance(data, dict):
        _vision_guard_record(False)
        return None

    norm = _normalize_vision(data)
    if not norm:
        _vision_guard_record(False)
        return None

    _vision_guard_record(True)
    return norm


def infer_blueprint(dd: DrawingData, *, default_thickness: float = 6.0,
                    default_fillet: float = 5.0,
                    vision: dict[str, Any] | None = None) -> dict[str, Any]:
    """由提取结果推断蓝图（与 parse.parse_blueprint 兼容）。

    vision 为多模态模型给出的候选值（见 vision_candidates）。启用时其值以
    ``status="inferred"``、``source="maas:vision"`` 进入 Spec，仍由置信度模型
    与确定性内核复核——**模型只提候选，不参与最终裁决**。
    """
    from .demo import PLATE_BLUEPRINT

    vparams: dict[str, dict[str, Any]] = (vision or {}).get("params") or {}

    def vget(pid: str) -> tuple[float, float] | None:
        item = vparams.get(pid)
        if not item:
            return None
        try:
            return float(item["value"]), float(item["confidence"])
        except (KeyError, TypeError, ValueError):
            return None

    vL, vW = vget("plate.L"), vget("plate.W")

    if not dd.rects and not (vL and vW):
        raise ValueError("未检测到零件外轮廓，无法推断整体尺寸")

    rect = max(dd.rects, key=lambda r: r.area) if dd.rects else None
    ocr_conf = 0.85 if dd.text_backend == "pdf" else 0.6

    # 整体尺寸：多模态候选优先，其次图纸文字
    if vL and vW:
        (L, conf_L), (W, conf_W) = vL, vW
        src_L = src_W = "maas:vision"
    else:
        nums = _numbers(dd.texts)
        ints = sorted({v for v, _, _ in nums if v >= 10}, reverse=True)
        if len(ints) < 2:
            raise ValueError("未能从图纸中识别出整体尺寸（长/宽），请人工录入")
        L, W = float(ints[0]), float(ints[1])
        conf_L = conf_W = ocr_conf
        src_L = src_W = "drawing:overall"

    vd = vget("hole.d")
    if vd:
        dia, dconf, dsrc = vd[0], vd[1], "maas:vision"
    else:
        dia, dconf = _diameter(dd.texts)
        dsrc = "drawing:hole_callout"
        if dia is None:
            dia, dconf = 6.5, 0.4
            dd.notes.append("未识别孔直径，暂用默认值 φ6.5（待确认）")

    # 比例尺：按外框长宽比与标注 L/W 的匹配度选择基准边（兼容竖版图纸）
    # 仅在"需要由像素换算孔位"时才是必需项；多模态已给出孔位时可跳过。
    scale: float | None = None
    scale_error: str | None = "未检测到零件外轮廓，无法推断整体尺寸"
    if rect is not None and rect.w > 0 and rect.h > 0 and L > 0 and W > 0:
        rw, rh = rect.w, rect.h
        ratio_rect = rw / rh
        ratio_lw = L / W

        if abs(ratio_rect - ratio_lw) <= 0.3 * ratio_lw:
            scale = rw / L                    # 横版：外框宽 = L
        elif abs((1.0 / ratio_rect) - ratio_lw) <= 0.3 * ratio_lw:
            scale = rh / L                    # 竖版：外框高 = L
            dd.notes.append("检测到竖版图纸，比例尺按外框高度换算")
        else:
            scale_error = (
                f"图纸长宽比({ratio_rect:.2f})与标注尺寸比({ratio_lw:.2f})"
                f"不匹配，请人工确认整体尺寸"
            )
        if scale is not None and scale <= 0:
            scale, scale_error = None, "图纸比例无法确定"
    elif L > 0 and W > 0:
        scale_error = "图纸比例无法确定"
    dd.scale_px_per_mm = scale

    holes: list[tuple[float, float]] = []
    hsrc, hconf = "drawing:hole_center", 0.8

    # 孔位：多模态候选优先（已是 mm 坐标，无需比例尺）
    vholes = (vision or {}).get("holes") or []
    for h in vholes[:4]:
        try:
            holes.append((round(float(h["x"]), 2), round(float(h["y"]), 2)))
        except (KeyError, TypeError, ValueError):
            continue
    if holes:
        hsrc = "maas:vision"
        confs = [float(h.get("confidence", 0.75)) for h in vholes[:len(holes)]]
        hconf = max(0.3, min(0.9, sum(confs) / len(confs)))

    if not holes:
        if scale is None or rect is None:
            raise ValueError(scale_error or "图纸比例无法确定")
        expected_r = (dia / 2) * scale if dia else 0.0
        cand = [c for c in dd.circles if rect.x0 < c.cx < rect.x1 and rect.y0 < c.cy < rect.y1]
        if expected_r > 0:
            # 用"期望孔半径"过滤异常圆（过大/过小），抑制 Hough 噪声
            cand = [c for c in cand if 0.6 * expected_r <= c.r <= 1.5 * expected_r]
        cand = _cluster(cand, dist=max(20.0, 1.2 * expected_r))
        cand = sorted(cand, key=lambda c: -c.r)[:4]

        for c in cand:
            x_mm = (c.cx - rect.x0) / scale
            y_mm = (rect.y1 - c.cy) / scale  # 图像 y 向下 -> 模型 y 向上
            holes.append((round(x_mm, 2), round(y_mm, 2)))
        holes = sorted(holes, key=lambda p: (round(p[1]), p[0]))
    if len(holes) < 4:
        dd.notes.append(f"仅识别到 {len(holes)} 个孔（期望 4），可人工补充")

    # 边距：多模态候选优先，否则取"每个孔到最近边距离"的中位数（多数孔一致的边距）
    per_min = [min(x, y, L - x, W - y) for x, y in holes]
    vm = vget("margin")
    if vm:
        margin, conf_M, src_M = vm[0], vm[1], "maas:vision"
    else:
        margin = round(_median(per_min), 1) if per_min else 15.0
        conf_M, src_M = 0.7, "rule:median_margin"
    outliers = [i for i, e in enumerate(per_min, start=1) if abs(e - margin) > 2.0]
    if outliers:
        dd.notes.append("孔位边距不一致（疑似标注冲突）：孔 " + ", ".join(f"h{i}" for i in outliers))

    # 板厚 / 圆角：多模态候选优先，否则沿用默认值（明确标注为推断）
    vT, vR = vget("plate.T"), vget("fillet.r")
    if vT:
        T, conf_T, src_T = vT[0], vT[1], "maas:vision"
    else:
        T, conf_T, src_T = default_thickness, 0.6, "no_side_view"
    if vR:
        fillet, conf_R, src_R = vR[0], vR[1], "maas:vision"
    else:
        fillet, conf_R, src_R = default_fillet, 0.6, "no_note"

    def _status_of(src: str) -> str:
        # 模型给出的值一律记为 inferred：它只是候选，需内核/人工复核
        return "inferred" if src == "maas:vision" else "observed"

    params: list[dict[str, Any]] = [
        {"id": "plate.L", "value": L, "confidence": conf_L, "status": _status_of(src_L), "source": src_L},
        {"id": "plate.W", "value": W, "confidence": conf_W, "status": _status_of(src_W), "source": src_W},
        {"id": "plate.T", "value": T, "confidence": conf_T, "status": "inferred", "source": src_T,
         "note": "" if vT else "图纸未提供厚度，暂用默认值"},
        {"id": "fillet.r", "value": fillet, "confidence": conf_R, "status": "inferred", "source": src_R,
         "note": "" if vR else "图纸未标注圆角，暂用默认值"},
        {"id": "hole.d", "value": dia, "confidence": dconf, "status": _status_of(dsrc), "source": dsrc},
        {"id": "margin", "value": margin, "confidence": conf_M, "status": "inferred", "source": src_M,
         "note": "" if vm else "由各孔最近边距离的中位数推断"},
    ]
    for i in range(1, 5):
        if i <= len(holes):
            x, y = holes[i - 1]
            params.append({"id": f"hole.x{i}", "value": x, "confidence": hconf,
                           "status": _status_of(hsrc), "source": hsrc})
            params.append({"id": f"hole.y{i}", "value": y, "confidence": hconf,
                           "status": _status_of(hsrc), "source": hsrc})

    return {
        "params": params,
        "derived": [],
        "features": PLATE_BLUEPRINT["features"],
        "constraints": PLATE_BLUEPRINT["constraints"],
        "overrides": [],
        "drawing": dd.to_dict(),
        "vision": {
            "used": bool(vision),
            "params": (vision or {}).get("params") or {},
            "holes": (vision or {}).get("holes") or [],
        },
    }


def parse_drawing(path: str, preference: str = "auto", dpi: int = 150,
                  use_vision: bool | None = None):
    """解析图纸文件 -> ParseResult。

    use_vision=None 表示自动：配置了 MaaS 多模态即启用；
    未配置模型时行为与接入前完全一致（纯确定性 + 本地 OCR）。
    """
    from .parse import parse_blueprint

    dd = extract_drawing(path, dpi=dpi)

    vision: dict[str, Any] | None = None
    if use_vision is not False:
        vision = vision_candidates(path)
        if vision:
            dd.notes.append("已启用 MaaS 多模态解析：模型值标记为 inferred，需确定性内核复核")
            for n in (vision.get("notes") or [])[:4]:
                dd.notes.append(f"多模态提示：{n}")

    bp = infer_blueprint(dd, vision=vision)
    result = parse_blueprint(bp, preference=preference)
    result.notes = list(dd.notes)
    result.drawing = dd.to_dict()
    if vision:
        result.drawing["vision"] = {
            "params": vision.get("params") or {},
            "holes": vision.get("holes") or [],
        }
    return result