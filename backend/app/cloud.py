"""华为云服务接入的统一配置与能力探测。

设计原则
--------
1. **全部可选**：任何服务未配置时，主闭环（解析 → 审查 → 修复 → 回归验证）
   完全不受影响，行为与未接入前一致。
2. **单一事实来源**：所有云服务开关集中在本模块，避免环境变量散落在各业务文件。
3. **可探测**：``status()`` 汇总各服务可用性，供 ``/api/meta`` 与前端展示。

涉及服务
--------
- MaaS 模型即服务（OpenAI 兼容）  → 大模型推理 / 多模态图纸理解
- OBS 对象存储                    → 证据包持久化、预签名下载
- FunctionGraph 函数工作流        → 长任务（建模/导出/证据打包）异步化
- CES 云监控                      → 调用量、时延、错误率指标上报

环境变量一览（全部可选）
------------------------
MaaS:      LLM_BASE_URL / LLM_API_KEY / LLM_MODEL / LLM_VISION_MODEL / LLM_VISION
OBS:       OBS_ENDPOINT / OBS_BUCKET / OBS_AK / OBS_SK / OBS_PREFIX
FunctionGraph: FN_ENDPOINT / FN_TOKEN / FN_TIMEOUT
CES:       CES_AK / CES_SK / CES_REGION / CES_PROJECT_ID / CES_NAMESPACE
"""
from __future__ import annotations

import importlib.util
import os
from typing import Any

# 指标命名空间默认值（CES 自定义指标需 namespace）
DEFAULT_CES_NAMESPACE = "Sourth/CADAgent"
DEFAULT_OBS_PREFIX = "evidence"


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def env(name: str, default: str = "") -> str:
    """读取环境变量并去除首尾空白。"""
    return (os.environ.get(name) or default).strip()


def truthy(value: str | None, *, default: bool = False) -> bool:
    """把 '1'/'true'/'yes'/'on' 视为真；未设置时返回 default。"""
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def module_available(name: str) -> bool:
    """不真正导入，仅探测模块是否可安装可用（避免副作用与慢导入）。"""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def mask(secret: str) -> str:
    """对密钥做掩码，保证状态输出不泄漏凭据。"""
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * (len(secret) - 8)}{secret[-4:]}"


def host_of(url: str) -> str:
    """从 URL 中取出 host，便于在界面上展示而不暴露路径与参数。"""
    if not url:
        return ""
    rest = url.split("://", 1)[-1]
    return rest.split("/", 1)[0]


# --------------------------------------------------------------------------- #
# 各服务配置读取
# --------------------------------------------------------------------------- #
def maas_config() -> dict[str, Any]:
    """MaaS（OpenAI 兼容）配置。"""
    base = env("LLM_BASE_URL").rstrip("/")
    return {
        "base_url": base,
        "host": host_of(base),
        "api_key": env("LLM_API_KEY"),
        "model": env("LLM_MODEL", "default"),
        # 多模态默认跟随总开关：配置了 base_url 即视为可用，可用 LLM_VISION=0 关闭
        "vision_model": env("LLM_VISION_MODEL") or env("LLM_MODEL", "default"),
        "vision_enabled": truthy(os.environ.get("LLM_VISION"), default=bool(base)),
    }


def obs_config() -> dict[str, Any]:
    """OBS 配置。"""
    return {
        "endpoint": env("OBS_ENDPOINT"),
        "bucket": env("OBS_BUCKET"),
        "ak": env("OBS_AK"),
        "sk": env("OBS_SK"),
        "prefix": env("OBS_PREFIX", DEFAULT_OBS_PREFIX).strip("/"),
    }


def fn_config() -> dict[str, Any]:
    """FunctionGraph 配置。"""
    return {
        "endpoint": env("FN_ENDPOINT"),
        "token": env("FN_TOKEN"),
        "timeout": float(env("FN_TIMEOUT", "60") or 60),
    }


def ces_config() -> dict[str, Any]:
    """CES 配置。"""
    return {
        "ak": env("CES_AK"),
        "sk": env("CES_SK"),
        "region": env("CES_REGION", "cn-southwest-2"),
        "project_id": env("CES_PROJECT_ID"),
        "namespace": env("CES_NAMESPACE", DEFAULT_CES_NAMESPACE),
    }


# --------------------------------------------------------------------------- #
# 可用性判断（配置齐全 + 依赖可导入）
# --------------------------------------------------------------------------- #
def maas_available() -> bool:
    return bool(env("LLM_BASE_URL"))


def vision_available() -> bool:
    cfg = maas_config()
    return bool(cfg["base_url"]) and bool(cfg["vision_enabled"])


def obs_sdk_available() -> bool:
    """官方 SDK（esdk-obs-python）是否可用。"""
    return module_available("obs")


def s3_fallback_available() -> bool:
    """S3 兼容协议兜底（OBS 支持 S3 API）是否可用。"""
    return module_available("boto3")


def obs_available() -> bool:
    cfg = obs_config()
    configured = all(cfg[k] for k in ("endpoint", "bucket", "ak", "sk"))
    return configured and (obs_sdk_available() or s3_fallback_available())


def fn_available() -> bool:
    return bool(env("FN_ENDPOINT"))


def ces_available() -> bool:
    cfg = ces_config()
    configured = bool(cfg["ak"] and cfg["sk"])
    return configured and module_available("huaweicloudsdkces")


# --------------------------------------------------------------------------- #
# 状态汇总（不发起任何网络请求，纯本地探测）
# --------------------------------------------------------------------------- #
def status() -> dict[str, Any]:
    """汇总所有华为云服务接入状态，供 /api/meta 与前端展示。"""
    m = maas_config()
    o = obs_config()
    f = fn_config()
    c = ces_config()

    obs_configured = all(o[k] for k in ("endpoint", "bucket", "ak", "sk"))
    ces_configured = bool(c["ak"] and c["sk"])

    return {
        "maas": {
            "configured": maas_available(),
            "available": maas_available(),
            "host": m["host"],
            "model": m["model"],
            "vision_enabled": bool(m["base_url"]) and bool(m["vision_enabled"]),
            "vision_model": m["vision_model"],
        },
        "obs": {
            "configured": obs_configured,
            "available": obs_available(),
            "bucket": o["bucket"],
            "endpoint": host_of(o["endpoint"]),
            "prefix": o["prefix"],
            "ak_masked": mask(o["ak"]),
            "sdk": "esdk-obs-python" if obs_sdk_available() else (
                "boto3(s3-compatible)" if s3_fallback_available() else "none"
            ),
        },
        "functiongraph": {
            "configured": fn_available(),
            "available": fn_available(),
            "endpoint_set": bool(f["endpoint"]),
        },
        "ces": {
            "configured": ces_configured,
            "available": ces_available(),
            "namespace": c["namespace"],
            "region": c["region"],
            "sdk": "huaweicloudsdkces" if module_available("huaweicloudsdkces") else "none",
        },
        "enabled_count": sum([
            maas_available(),
            obs_available(),
            fn_available(),
            ces_available(),
        ]),
    }
