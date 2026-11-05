"""对象存储 OBS 适配层（可选）。

职责
----
- 把证据包（manifest/report/STEP/STL）上传到 OBS，形成"云端可校验证据链"
- 生成预签名 URL，让前端/评委直接下载产物，无需经过本服务中转
- 探测连通性（head bucket），供 /api/cloud/status 做自检

设计约束
--------
1. **绝不抛出**：所有函数在失败时返回带 ``ok=False`` 与 ``error`` 的字典，
   主流程（审查/修复/回归）永不因对象存储故障而中断。
2. **双后端**：优先官方 SDK ``esdk-obs-python``；缺失时退回 S3 兼容协议
   （OBS 支持 S3 API，需 ``boto3``）。
3. **未配置即静默**：没有任何凭据时所有调用快速返回 ``ok=False``，
   行为与未接入前一致。
"""
from __future__ import annotations

import mimetypes
import os
from typing import Any

from .cloud import obs_config, obs_sdk_available, s3_fallback_available

BACKEND_OBS = "obs"
BACKEND_S3 = "s3"
BACKEND_NONE = "none"


# --------------------------------------------------------------------------- #
# 配置与客户端
# --------------------------------------------------------------------------- #
def _normalized_endpoint(endpoint: str) -> str:
    """boto3 需要带 scheme 的 endpoint；OBS SDK 接受裸域名。"""
    if not endpoint:
        return ""
    if "://" in endpoint:
        return endpoint
    return f"https://{endpoint}"


def backend() -> str:
    """当前可用的后端实现。"""
    if obs_sdk_available():
        return BACKEND_OBS
    if s3_fallback_available():
        return BACKEND_S3
    return BACKEND_NONE


def _error(reason: str) -> dict[str, Any]:
    return {"ok": False, "backend": backend(), "error": reason}


def _obs_client():
    """创建 OBS SDK 客户端（调用方负责 close）。"""
    from obs import ObsClient  # type: ignore

    cfg = obs_config()
    return ObsClient(
        access_key_id=cfg["ak"],
        secret_access_key=cfg["sk"],
        server=_normalized_endpoint(cfg["endpoint"]),
    )


def _s3_client():
    import boto3  # type: ignore

    cfg = obs_config()
    return boto3.client(
        "s3",
        endpoint_url=_normalized_endpoint(cfg["endpoint"]),
        aws_access_key_id=cfg["ak"],
        aws_secret_access_key=cfg["sk"],
        region_name=cfg.get("region") or "cn-southwest-2",
    )


def _precheck() -> dict[str, Any] | None:
    """通用前置校验：未配置/无后端时返回错误字典。"""
    cfg = obs_config()
    missing = [k for k in ("endpoint", "bucket", "ak", "sk") if not cfg[k]]
    if missing:
        return _error(f"OBS 未配置（缺少 {', '.join('OBS_' + m.upper() for m in missing)}）")
    if backend() == BACKEND_NONE:
        return _error("未安装 OBS 依赖（pip install esdk-obs-python 或 boto3）")
    return None


def object_key(filename: str, *, prefix: str | None = None) -> str:
    """构造对象 key：``<prefix>/<filename>``，自动去掉多余斜杠。"""
    cfg = obs_config()
    p = (prefix if prefix is not None else cfg["prefix"]).strip("/")
    name = filename.lstrip("/").replace("\\", "/")
    return f"{p}/{name}" if p else name


# --------------------------------------------------------------------------- #
# 上传
# --------------------------------------------------------------------------- #
def put_bytes(data: bytes, key: str, *, content_type: str | None = None) -> dict[str, Any]:
    """上传内存字节。返回 {ok, backend, key, etag, bytes} 或 {ok:False,error}。"""
    err = _precheck()
    if err:
        return err

    cfg = obs_config()
    ctype = content_type or "application/octet-stream"

    try:
        if backend() == BACKEND_OBS:
            client = _obs_client()
            try:
                resp = client.putContent(cfg["bucket"], key, data, metadata={"Content-Type": ctype})
                status = getattr(resp, "status", 0)
                if status >= 300:
                    return _error(f"OBS putContent 失败: status={status} {getattr(resp, 'errorMessage', '')}")
                etag = getattr(getattr(resp, "body", None), "etag", "")
                return {"ok": True, "backend": BACKEND_OBS, "key": key,
                        "etag": (etag or "").strip('"'), "bytes": len(data)}
            finally:
                try:
                    client.close()
                except Exception:
                    pass

        s3 = _s3_client()
        s3.put_object(Bucket=cfg["bucket"], Key=key, Body=data, ContentType=ctype)
        head = s3.head_object(Bucket=cfg["bucket"], Key=key)
        return {"ok": True, "backend": BACKEND_S3, "key": key,
                "etag": (head.get("ETag") or "").strip('"'), "bytes": len(data)}
    except Exception as e:  # 任何网络/鉴权异常都不外抛
        return _error(f"{type(e).__name__}: {e}")


def put_file(local_path: str, key: str, *, content_type: str | None = None) -> dict[str, Any]:
    """上传本地文件。"""
    err = _precheck()
    if err:
        return err
    if not os.path.isfile(local_path):
        return _error(f"文件不存在: {local_path}")

    cfg = obs_config()
    ctype = content_type or mimetypes.guess_type(local_path)[0] or "application/octet-stream"

    try:
        if backend() == BACKEND_OBS:
            client = _obs_client()
            try:
                resp = client.putFile(cfg["bucket"], key, local_path,
                                      metadata={"Content-Type": ctype})
                status = getattr(resp, "status", 0)
                if status >= 300:
                    return _error(f"OBS putFile 失败: status={status} {getattr(resp, 'errorMessage', '')}")
                etag = getattr(getattr(resp, "body", None), "etag", "")
                return {"ok": True, "backend": BACKEND_OBS, "key": key,
                        "etag": (etag or "").strip('"'), "bytes": os.path.getsize(local_path)}
            finally:
                try:
                    client.close()
                except Exception:
                    pass

        s3 = _s3_client()
        s3.upload_file(local_path, cfg["bucket"], key,
                       ExtraArgs={"ContentType": ctype})
        head = s3.head_object(Bucket=cfg["bucket"], Key=key)
        return {"ok": True, "backend": BACKEND_S3, "key": key,
                "etag": (head.get("ETag") or "").strip('"'), "bytes": os.path.getsize(local_path)}
    except Exception as e:
        return _error(f"{type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# 下载链接与自检
# --------------------------------------------------------------------------- #
def signed_url(key: str, *, expires: int = 3600) -> str | None:
    """生成预签名下载 URL；失败返回 None。"""
    err = _precheck()
    if err:
        return None

    cfg = obs_config()
    try:
        if backend() == BACKEND_OBS:
            client = _obs_client()
            try:
                resp = client.createSignedUrl("GET", cfg["bucket"], key, expires=expires)
                return getattr(resp, "signedUrl", None)
            finally:
                try:
                    client.close()
                except Exception:
                    pass

        s3 = _s3_client()
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": cfg["bucket"], "Key": key},
            ExpiresIn=expires,
        )
    except Exception:
        return None


def probe() -> dict[str, Any]:
    """连通性自检：确认桶可访问（会发起一次网络请求）。"""
    err = _precheck()
    if err:
        return err

    cfg = obs_config()
    try:
        if backend() == BACKEND_OBS:
            client = _obs_client()
            try:
                resp = client.headBucket(cfg["bucket"])
                status = getattr(resp, "status", 0)
                return {
                    "ok": status < 300,
                    "backend": BACKEND_OBS,
                    "bucket": cfg["bucket"],
                    "status": status,
                    "error": "" if status < 300 else f"headBucket status={status}",
                }
            finally:
                try:
                    client.close()
                except Exception:
                    pass

        s3 = _s3_client()
        s3.head_bucket(Bucket=cfg["bucket"])
        return {"ok": True, "backend": BACKEND_S3, "bucket": cfg["bucket"], "status": 200, "error": ""}
    except Exception as e:
        return {"ok": False, "backend": backend(), "bucket": cfg["bucket"],
                "error": f"{type(e).__name__}: {e}"}


def upload_files(paths: list[str], *, prefix: str, signed: bool = True,
                 expires: int = 3600) -> dict[str, Any]:
    """批量上传，返回 {ok, backend, objects:[{path,key,etag,bytes,url}], failed:[...]}。"""
    err = _precheck()
    if err:
        return {"ok": False, "backend": backend(), "objects": [], "failed": [], "error": err.get("error")}

    objects: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for path in paths:
        if not os.path.isfile(path):
            failed.append({"path": path, "error": "文件不存在"})
            continue
        name = os.path.basename(path)
        key = object_key(f"{prefix}/{name}" if prefix else name)
        res = put_file(path, key)
        if not res.get("ok"):
            failed.append({"path": path, "error": res.get("error")})
            continue
        item = {
            "path": name,
            "key": key,
            "etag": res.get("etag", ""),
            "bytes": res.get("bytes", 0),
        }
        if signed:
            url = signed_url(key, expires=expires)
            if url:
                item["url"] = url
        objects.append(item)

    return {
        "ok": not failed,
        "backend": backend(),
        "bucket": obs_config()["bucket"],
        "objects": objects,
        "failed": failed,
        "error": "" if not failed else f"{len(failed)} 个文件上传失败",
    }
