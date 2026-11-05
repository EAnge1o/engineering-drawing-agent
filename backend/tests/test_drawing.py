"""真实图纸解析测试（基于 samples/ 下的 PDF 与 PNG 样例）。

若样例缺失则跳过（先运行 `python scripts/export_samples.py` 生成）。
"""
import os

import pytest

from app.audit import audit
from app.drawing import extract_drawing, infer_blueprint, parse_drawing

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLES = os.path.join(ROOT, "samples")


def _sample(name: str) -> str:
    p = os.path.join(SAMPLES, name)
    if not os.path.exists(p):
        pytest.skip(f"缺少样例 {p}（先运行 export_samples.py）")
    return p


def test_extract_pdf_text_and_shapes():
    pdf = _sample("plate_normal.pdf")
    dd = extract_drawing(pdf)
    assert dd.text_backend == "pdf"
    joined = " ".join(t.text for t in dd.texts)
    assert "120" in joined and "80" in joined
    assert dd.rects, "应检测到外轮廓"
    assert len(dd.circles) >= 4, f"应检测到至少 4 个孔，实际 {len(dd.circles)}"


def test_infer_blueprint_overall_size():
    pdf = _sample("plate_normal.pdf")
    dd = extract_drawing(pdf)
    bp = infer_blueprint(dd)
    L = next(p["value"] for p in bp["params"] if p["id"] == "plate.L")
    W = next(p["value"] for p in bp["params"] if p["id"] == "plate.W")
    d = next(p["value"] for p in bp["params"] if p["id"] == "hole.d")
    assert abs(L - 120) < 2, L
    assert abs(W - 80) < 2, W
    assert abs(d - 6.5) < 0.5, d


def test_normal_pdf_has_no_issue():
    res = parse_drawing(_sample("plate_normal.pdf"))
    assert audit(res.spec) == []


def test_defect_pdf_detects_conflict():
    res = parse_drawing(_sample("plate_defect.pdf"))
    codes = {i.constraint_id for i in audit(res.spec)}
    # 右上孔位与推断边距冲突 -> 孔位越界
    assert any(c and c.startswith("c_h") and c.endswith("_inside") for c in codes), codes


def test_png_raster_shapes_without_ocr():
    """位图无 OCR 时仍应能检测图形（文字交由人工录入）。"""
    png = _sample("plate_normal.png")
    dd = extract_drawing(png)
    assert dd.text_backend in {"manual", "pytesseract", "tesseract-cli"}
    assert dd.rects, "位图也应检测到外轮廓"
    assert len(dd.circles) >= 3