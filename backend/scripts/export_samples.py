"""生成演示样例：蓝图 JSON + 示意二维工程图 PNG。

运行：在 backend 目录下执行 `python scripts/export_samples.py`
输出：
  samples/plate_normal.blueprint.json
  samples/plate_defect.blueprint.json
  samples/plate_normal.png / plate_defect.png（带尺寸标注的示意图）
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

from app.demo import PLATE_BLUEPRINT, plate_blueprint  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLES = os.path.join(ROOT, "samples")


def _blueprint_from(bp: dict) -> dict:
    """把蓝图整理为"零件 + 孔"的展示用结构。"""
    L = next(p["value"] for p in bp["params"] if p["id"] == "plate.L")
    W = next(p["value"] for p in bp["params"] if p["id"] == "plate.W")
    d = next(p["value"] for p in bp["params"] if p["id"] == "hole.d")
    overrides = {o["id"]: o["value"] for o in bp.get("overrides", [])}
    holes = []
    for i in range(1, 5):
        xid, yid = f"hole.x{i}", f"hole.y{i}"
        x = overrides.get(xid, next((v["value"] for v in bp["derived"] if v["id"] == xid), 0))
        y = overrides.get(yid, next((v["value"] for v in bp["derived"] if v["id"] == yid), 0))
        holes.append({"id": f"hole_h{i}", "x": x, "y": y, "d": d})
    return {"length": L, "width": W, "hole_d": d, "holes": holes}


def draw_drawing(geom: dict, path: str, title: str) -> None:
    """绘制简易二维工程图（演示"上传图纸"输入）。"""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        print(f"  (跳过绘图，Pillow 不可用) {path}")
        return

    W, H = 900, 700
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    L, Wd = geom["length"], geom["width"]
    scale = min((W - 240) / L, (H - 240) / Wd)
    ox = (W - L * scale) / 2
    oy = (H - Wd * scale) / 2

    def p(x, y):
        return (ox + x * scale, oy + (Wd - y) * scale)

    d.rectangle([p(0, Wd), p(L, 0)], outline="black", width=3)
    for h in geom["holes"]:
        cx, cy = p(h["x"], h["y"])
        r = h["d"] / 2 * scale
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline="black", width=2)
        d.line([cx - 7, cy, cx + 7, cy], fill="black")
        d.line([cx, cy - 7, cx, cy + 7], fill="black")

    d.text((ox + L * scale / 2, oy + Wd * scale + 24), f"{L:.0f}", fill="black", anchor="mm")
    d.text((ox - 28, oy + Wd * scale / 2), f"{Wd:.0f}", fill="black", anchor="mm")
    d.text((ox + L * scale + 14, oy - 6), "4x D6.5", fill="black")
    d.text((20, 20), title, fill="black")
    d.text((20, H - 30), "UNIT mm  SCALE 1:1", fill="black")
    img.save(path)


def draw_pdf(geom: dict, path: str, title: str) -> None:
    """绘制矢量 PDF 工程图（文字层可被 PyMuPDF 直接提取）。"""
    try:
        import pymupdf as fitz
    except Exception:
        try:
            import fitz
        except Exception:
            print(f"  (跳过 PDF，PyMuPDF 不可用) {path}")
            return

    W, H = 900, 700
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)

    L, Wd = geom["length"], geom["width"]
    scale = min((W - 240) / L, (H - 240) / Wd)
    ox = (W - L * scale) / 2
    oy = (H - Wd * scale) / 2

    def p(x, y):
        return (ox + x * scale, oy + (Wd - y) * scale)

    x0, y0 = p(0, Wd)
    x1, y1 = p(L, 0)
    page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=(0, 0, 0), width=2)

    for hole in geom["holes"]:
        cx, cy = p(hole["x"], hole["y"])
        r = hole["d"] / 2 * scale
        page.draw_circle((cx, cy), r, color=(0, 0, 0), width=1.5)
        page.draw_line((cx - 7, cy), (cx + 7, cy), color=(0, 0, 0))
        page.draw_line((cx, cy - 7), (cx, cy + 7), color=(0, 0, 0))

    page.insert_text((ox + L * scale / 2 - 8, oy + Wd * scale + 22), f"{L:.0f}", fontsize=14)
    page.insert_text((ox - 36, oy + Wd * scale / 2 + 4), f"{Wd:.0f}", fontsize=14)
    page.insert_text((ox + L * scale + 12, oy - 4), "4x D6.5", fontsize=14)
    page.insert_text((20, 28), title, fontsize=14)
    page.insert_text((20, H - 22), "UNIT mm SCALE 1:1", fontsize=12)

    doc.save(path)
    doc.close()


def main() -> None:
    os.makedirs(SAMPLES, exist_ok=True)

    variants = [
        ("plate_normal", plate_blueprint(with_defect=False), "PLATE (NORMAL)"),
        ("plate_defect", plate_blueprint(with_defect=True), "PLATE (DEFECT)"),
    ]
    for name, bp, title in variants:
        bp_path = os.path.join(SAMPLES, f"{name}.blueprint.json")
        with open(bp_path, "w", encoding="utf-8") as fh:
            json.dump(bp, fh, ensure_ascii=False, indent=2)
        geom = _blueprint_from(bp)
        png_path = os.path.join(SAMPLES, f"{name}.png")
        draw_drawing(geom, png_path, title)
        pdf_path = os.path.join(SAMPLES, f"{name}.pdf")
        draw_pdf(geom, pdf_path, title)
        print(f"  生成 {bp_path} / {png_path} / {pdf_path}")

    # 顺带保存一份原始蓝图模板
    with open(os.path.join(SAMPLES, "plate_template.json"), "w", encoding="utf-8") as fh:
        json.dump(PLATE_BLUEPRINT, fh, ensure_ascii=False, indent=2)
    print(f"样例已输出到 {SAMPLES}")


if __name__ == "__main__":
    main()