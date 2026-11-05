"""SQLite + JSON 持久化：任务、参数、修复历史与证据。"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from typing import Any

from .models import Spec

# 绝对路径：避免随进程 CWD 漂移到不同目录
DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent.db")

_CREATE = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    created_at REAL,
    updated_at REAL,
    state TEXT,
    payload TEXT
)
"""


def _connect(db: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db, timeout=5)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    return conn


def init_db(db: str = DEFAULT_DB) -> None:
    with closing(_connect(db)) as conn:
        conn.execute(_CREATE)
        conn.commit()


def _payload(result: dict[str, Any], spec: Spec | None) -> str:
    data: dict[str, Any] = dict(result)
    if spec is not None:
        data["spec"] = spec.to_dict()
    return json.dumps(data, ensure_ascii=False)


def save_task(
    task_id: str,
    result: dict[str, Any],
    spec: Spec | None = None,
    state: str = "DONE",
    db: str = DEFAULT_DB,
) -> None:
    init_db(db)
    now = time.time()
    with closing(_connect(db)) as conn:
        conn.execute(
            "INSERT INTO tasks(id, created_at, updated_at, state, payload) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, "
            "state=excluded.state, payload=excluded.payload",
            (task_id, now, now, state, _payload(result, spec)),
        )
        conn.commit()


def load_task(task_id: str, db: str = DEFAULT_DB) -> dict[str, Any] | None:
    init_db(db)
    with closing(_connect(db)) as conn:
        row = conn.execute("SELECT payload FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return json.loads(row[0]) if row else None


def list_tasks(db: str = DEFAULT_DB) -> list[dict[str, Any]]:
    init_db(db)
    with closing(_connect(db)) as conn:
        rows = conn.execute(
            "SELECT id, state, updated_at FROM tasks ORDER BY updated_at DESC"
        ).fetchall()
    # 键名与内存任务统一为 task_id，并保留 updated_at
    return [{"task_id": r[0], "state": r[1], "updated_at": r[2]} for r in rows]