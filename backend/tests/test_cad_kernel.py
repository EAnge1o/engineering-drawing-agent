"""几何内核（CadQuery）验证：真实建模与 STEP/STL 导出。"""
import os

import pytest

from app.cad import build_plate, cadquery_available, export_step_stl, geometry_summary
from app.demo import build_plate_spec

pytestmark = pytest.mark.skipif(not cadquery_available(), reason="CadQuery 未安装")


def test_build_plate_volume_matches_summary():
    spec = build_plate_spec(with_defect=False)
    wp = build_plate(spec)
    assert wp is not None

    vol = wp.val().Volume()
    approx = geometry_summary(spec)["volume"]
    # 圆角会略微削减体积，允许 5% 误差
    assert abs(vol - approx) / approx < 0.05


def test_export_step_and_stl(tmp_path):
    spec = build_plate_spec(with_defect=False)
    paths = export_step_stl(spec, str(tmp_path))

    assert "step" in paths and "stl" in paths
    step_text = open(paths["step"], encoding="utf-8", errors="ignore").read()
    assert "MANIFOLD_SOLID_BREP" in step_text
    assert os.path.getsize(paths["stl"]) > 1000