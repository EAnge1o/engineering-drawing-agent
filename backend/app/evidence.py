"""证据链：为每次任务生成可校验的证据包（本地 + 可选华为云 OBS）。

产出结构：
    <evidence_dir>/<task_id>/
        manifest.json     证据清单（时间戳、文件哈希、来源、云端对象 key）
        report.json       审查与修复报告
        model.step/.stl   模型（若几何内核可用）

"证据可校验"是评审关注点：manifest 记录每个文件的 SHA-256 与生成时间。
配置 OBS 后，证据包会同步上传到对象存储，manifest 额外记录 **对象 key + ETag**，
配合 OBS 版本控制/保留策略即可证明"生成后未被篡改"。
上传失败不影响本地证据包，主流程不会中断。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from typing import Any


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _upload_objects(task_dir: str, manifest: dict[str, Any], *,
                    signed: bool) -> dict[str, Any] | None:
    """把 manifest.files 里的文件批量上传 OBS，并把 key/etag 回填到条目上。"""
    from . import obs as obs_mod

    paths = [os.path.join(task_dir, f["path"]) for f in manifest.get("files", [])]
    res = obs_mod.upload_files(paths, prefix=manifest["task_id"], signed=signed)
    if not res.get("objects"):
        return None

    by_name = {o["path"]: o for o in res["objects"]}
    for item in manifest.get("files", []):
        obj = by_name.get(item["path"])
        if obj:
            item["obs_key"] = obj["key"]
            item["etag"] = obj.get("etag", "")
            if obj.get("url"):
                item["url"] = obj["url"]

    return {
        "backend": res.get("backend"),
        "bucket": res.get("bucket"),
        "ok": res.get("ok"),
        "objects": res.get("objects", []),
        "failed": res.get("failed", []),
    }


def _upload_manifest(manifest_path: str, storage: dict[str, Any], *,
                     signed: bool) -> None:
    """最后上传 manifest 自身，使其成为"根证据"。"""
    from . import obs as obs_mod

    key = obs_mod.object_key(f"{storage.get('task_id', '')}/manifest.json".lstrip("/"))
    res = obs_mod.put_file(manifest_path, key)
    if res.get("ok"):
        storage["manifest_key"] = key
        storage["manifest_etag"] = res.get("etag", "")
        if signed:
            url = obs_mod.signed_url(key)
            if url:
                storage["manifest_url"] = url
    else:
        storage.setdefault("failed", []).append({"path": "manifest.json", "error": res.get("error")})


def build_evidence(
    task_id: str,
    result: dict[str, Any],
    *,
    outdir: str,
    extra_files: list[str] | None = None,
    spec_snapshot: dict[str, Any] | None = None,
    upload: bool | None = None,
    signed_urls: bool = True,
) -> dict[str, Any]:
    """写入报告与清单，返回 manifest。

    upload=None 表示自动：配置了 OBS 就上传；显式传 False 可强制仅本地。
    """
    task_dir = os.path.join(outdir, task_id)
    os.makedirs(task_dir, exist_ok=True)

    report_path = os.path.join(task_dir, "report.json")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump({"result": result, "spec": spec_snapshot}, fh, ensure_ascii=False, indent=2)

    files: list[dict[str, Any]] = [{
        "path": "report.json",
        "sha256": _sha256(report_path),
        "bytes": os.path.getsize(report_path),
        "role": "审查与修复报告",
    }]
    for idx, path in enumerate(extra_files or []):
        if not os.path.exists(path):
            continue
        # 落地进证据目录，使 verify 能按清单路径重算哈希
        name = os.path.basename(path)
        dest = os.path.join(task_dir, name)
        if os.path.exists(dest) and os.path.abspath(path) != os.path.abspath(dest):
            name = f"{idx}_{name}"                     # 同名来源防覆盖
            dest = os.path.join(task_dir, name)
        if os.path.abspath(path) != os.path.abspath(dest):
            shutil.copy2(path, dest)
        files.append({
            "path": name,
            "sha256": _sha256(dest),
            "bytes": os.path.getsize(dest),
            "role": "模型产物",
        })

    manifest = {
        "task_id": task_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "created_ts": time.time(),
        "state": result.get("state"),
        "budget": result.get("budget"),
        "files": files,
    }

    # 可选：同步到 OBS（失败不阻断，本地证据包仍然完整可校验）
    if upload is None:
        from .cloud import obs_available

        upload = obs_available()

    storage: dict[str, Any] | None = None
    if upload:
        storage = _upload_objects(task_dir, manifest, signed=signed_urls)
        if storage:
            storage["task_id"] = task_id
            manifest["storage"] = storage

    manifest_path = os.path.join(task_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    if storage:
        _upload_manifest(manifest_path, storage, signed=signed_urls)
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)

    manifest["dir"] = task_dir
    manifest["manifest_path"] = manifest_path
    return manifest


def verify_evidence(manifest_path: str) -> dict[str, Any]:
    """校验证据包完整性（逐文件重算哈希）。"""
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    base = os.path.dirname(manifest_path)
    checks = []
    for item in manifest.get("files", []):
        p = os.path.join(base, item["path"])
        ok = os.path.exists(p) and _sha256(p) == item["sha256"]
        checks.append({"path": item["path"], "ok": ok})
    return {
        "task_id": manifest.get("task_id"),
        "all_ok": all(c["ok"] for c in checks) if checks else False,
        "checks": checks,
    }