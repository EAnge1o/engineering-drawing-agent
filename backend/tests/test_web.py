"""Web 层测试：静态资源存在性（文件系统）+ 可选 HTTP 冒烟。

本机环境可能禁止本地回环连接，故 HTTP 冒烟默认跳过；
需要时设置环境变量 RUN_HTTP_TESTS=1 启用。
"""
import os

import pytest

# backend/tests/test_web.py -> backend -> C:/Sourth -> frontend
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND = os.path.join(ROOT, "frontend")

ESM_ENTRIES = [
    "preact/dist/preact.mjs",
    "preact/hooks/dist/hooks.mjs",
    "htm/dist/htm.module.js",
    "three/build/three.module.js",
]
SRC_FILES = [
    "src/app.js",
    "src/api.js",
    "src/html.js",
    "src/icons.js",
    "src/store.js",
    "src/styles/tokens.css",
    "src/styles/ui.css",
    "src/components/TopBar.js",
    "src/components/StepRail.js",
    "src/components/DropZone.js",
    "src/components/ViewerPanel.js",
    "src/components/Inspector.js",
    "src/components/IssueList.js",
    "src/components/FixTimeline.js",
    "src/components/DiffCompare.js",
    "src/components/Stat.js",
    "src/components/Toast.js",
    "src/components/Sidebar.js",
    "src/components/AgentStatus.js",
    "src/components/ReviewQueue.js",
    "src/components/ConfirmDialog.js",
]


def test_frontend_index_has_importmap():
    idx = os.path.join(FRONTEND, "index.html")
    assert os.path.exists(idx)
    text = open(idx, encoding="utf-8").read()
    assert "importmap" in text
    for entry in ESM_ENTRIES:
        assert entry in text, entry


def test_frontend_and_vendored_modules_exist():
    for rel in SRC_FILES:
        assert os.path.exists(os.path.join(FRONTEND, rel)), rel
    for entry in ESM_ENTRIES:
        assert os.path.exists(os.path.join(FRONTEND, "node_modules", entry)), entry


@pytest.mark.skipif(
    os.environ.get("RUN_HTTP_TESTS") != "1",
    reason="默认跳过 HTTP 冒烟（设置 RUN_HTTP_TESTS=1 启用；本机可能禁止回环连接）",
)
def test_http_smoke():
    from fastapi.testclient import TestClient

    from serve import app

    client = TestClient(app)
    assert client.get("/api/health").json()["ok"] is True
    assert "工程图纸建模与自纠错" in client.get("/").text
    for path in ["/src/app.js", "/node_modules/preact/dist/preact.mjs"]:
        assert client.get(path).status_code == 200

    r = client.post("/api/tasks", json={"with_defect": True, "task_id": "T-HTTP"})
    assert any(i["constraint_id"] == "c_h4_inside" for i in r.json()["issues"])
    f = client.post("/api/tasks/T-HTTP/fix", json={"budget": 5, "mode": "A1"})
    assert f.json()["state"] == "DONE"