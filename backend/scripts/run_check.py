"""启动自检：尝试绑定端口并短时启动服务，端到端验证 HTTP 可用性。

若本机禁用回环 socket（WinError 10051），会明确报告并给出本地运行指引。
运行：在 backend 目录下执行 `python scripts/run_check.py`
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass


def check_bind(host: str, port: int) -> tuple[bool, object]:
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, port))
        return True, None
    except OSError as e:  # pragma: no cover
        return False, e
    finally:
        s.close()


def post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    host = "127.0.0.1"
    port = int(os.environ.get("PORT", "8000"))

    ok, err = check_bind(host, port)
    print(f"[bind] {host}:{port} -> {'OK' if ok else f'FAIL: {err}'}")
    if not ok:
        print("\n本机禁用了本地回环 socket，无法在当前环境启动 HTTP 服务。")
        print("请在本地终端执行：  cd backend && python serve.py   →   http://127.0.0.1:8000")
        return 2

    import uvicorn

    from serve import app

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(3.0)

    exit_code = 0
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=10) as r:
            print("[health]", r.status, r.read().decode("utf-8"))

        with urllib.request.urlopen(f"http://{host}:{port}/", timeout=10) as r:
            html = r.read().decode("utf-8", "ignore")
            print("[index]", r.status, "| 含标题:", "工程图纸建模与自纠错" in html, "| 字节:", len(html))

        for path in ["/src/app.js", "/src/styles/tokens.css", "/node_modules/preact/dist/preact.mjs",
                     "/node_modules/three/build/three.module.js",
                     "/node_modules/three/examples/jsm/controls/OrbitControls.js"]:
            with urllib.request.urlopen(f"http://{host}:{port}{path}", timeout=10) as r:
                print(f"[static] {r.status} {path}")

        created = post(f"http://{host}:{port}/api/tasks", {"with_defect": True, "task_id": "T-RUN"})
        print("[create] issues:", len(created["issues"]),
              "| 首条:", created["issues"][0]["constraint_id"] if created["issues"] else "-")

        meta = json.loads(urllib.request.urlopen(f"http://{host}:{port}/api/meta", timeout=10).read().decode())
        print("[meta] cadquery:", meta["cadquery_available"], "| llm:", meta["llm_available"])

        res = post(f"http://{host}:{port}/api/tasks/T-RUN/fix", {"budget": 5, "mode": "A1"})
        print("[fix] state:", res["state"], "| resolved:", res["resolved"], "| remaining:", res["remaining"])

        cmp_ = json.loads(urllib.request.urlopen(f"http://{host}:{port}/api/tasks/T-RUN/compare", timeout=10).read().decode())
        print("[compare] 变更参数:", cmp_["changed_params"], "| 已解决:", cmp_["resolved"])

        ev = post(f"http://{host}:{port}/api/tasks/T-RUN/evidence", {})
        print("[evidence] 校验:", ev["verification"]["all_ok"], "| 文件数:", len(ev["manifest"]["files"]))

        print(f"\n服务已在 http://{host}:{port} 正常响应（脚本结束即停止）。")
    except Exception as e:  # pragma: no cover
        print("[http] 请求失败:", type(e).__name__, e)
        exit_code = 3
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())