"""启动服务：后端 API + 前端静态资源（同源，无需 CORS 与前端构建）。

运行：在 backend 目录下执行 `python serve.py`，浏览器打开 http://127.0.0.1:8000
"""
from __future__ import annotations

import os

import uvicorn
from fastapi.staticfiles import StaticFiles

from app.api import app

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()