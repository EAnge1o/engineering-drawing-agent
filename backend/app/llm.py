"""大模型适配层（OpenAI 兼容）。

用途：为图纸理解、疑点归纳、修复说明提供"可选"的模型增强。
默认**不启用**；未配置时全部走确定性路径，主闭环（审查/修复/回归）不受影响。

支持华为云 MaaS（模型即服务）等提供 OpenAI 兼容端点的服务：
    set LLM_BASE_URL=https://api.modelarts-maas.com/openai/v1
    set LLM_API_KEY=***
    set LLM_MODEL=deepseek-v4.1-flash

多模态（位图图纸理解）：
    set LLM_VISION_MODEL=deepseek-v4.1-flash-1017   # 可选，默认复用 LLM_MODEL
    set LLM_VISION=0                                # 可选，显式关闭多模态

**模型只提供候选值，不参与最终裁决**：所有模型产出在 evidence 中标记为
``status=inferred``、``source=maas:vision``，由确定性内核与规则引擎复核。
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any

TIMEOUT = 20.0
# 多模态请求需上传图片，耗时显著长于纯文本，单独给更宽松的超时
VISION_TIMEOUT = 90.0
# 送模型的图片最长边（px）：兼顾标注可读性与请求体大小
VISION_MAX_SIDE = 1600
VISION_JPEG_QUALITY = 85


def llm_available() -> bool:
    return bool(os.environ.get("LLM_BASE_URL"))


def vision_available() -> bool:
    """多模态是否可用：配置了 base_url 且未被 LLM_VISION=0 显式关闭。"""
    from .cloud import vision_available as _vision_available

    return _vision_available()


# --------------------------------------------------------------------------- #
# 图片编码（PDF 自动光栅化）
# --------------------------------------------------------------------------- #
def _render_pdf_page(path: str, dpi: int = 150):
    """把 PDF 首页渲染为 BGR ndarray；依赖 PyMuPDF。"""
    import numpy as np

    try:
        import pymupdf as fitz
    except Exception:  # pragma: no cover - 兼容旧包名
        import fitz  # type: ignore

    doc = fitz.open(path)
    try:
        pm = doc[0].get_pixmap(dpi=dpi)
        img = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, pm.n)
        return img[:, :, :3][:, :, ::-1].copy()  # RGB -> BGR
    finally:
        doc.close()


def _shrink_bgr(img, max_side: int = VISION_MAX_SIDE):
    """按最长边等比缩小，避免请求体过大被网关拒绝。"""
    import cv2

    h, w = img.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return img
    scale = max_side / float(longest)
    return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def encode_image_for_vision(path: str, *, max_side: int = VISION_MAX_SIDE) -> tuple[bytes, str]:
    """把图纸文件编码为可内联的 (bytes, mime)。

    - PDF：渲染首页后按 JPEG 编码
    - 位图：优先 OpenCV 缩放后 JPEG；无 OpenCV 时退回原文件字节
    """
    ext = os.path.splitext(path)[1].lower()
    try:
        import cv2

        img = _render_pdf_page(path) if ext == ".pdf" else cv2.imread(path)
        if img is not None:
            img = _shrink_bgr(img, max_side)
            ok, buf = cv2.imencode(
                ".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), VISION_JPEG_QUALITY]
            )
            if ok:
                return buf.tobytes(), "image/jpeg"
    except Exception:
        pass

    # 兜底：直接读原始文件（仅适用于位图；PDF 无 OpenCV 时无法内联）
    if ext == ".pdf":
        raise RuntimeError("多模态解析 PDF 需要 OpenCV + PyMuPDF（pip install opencv-python pymupdf）")
    with open(path, "rb") as fh:
        data = fh.read()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    return data, mime


# --------------------------------------------------------------------------- #
# 调用
# --------------------------------------------------------------------------- #
def _post_chat(body: dict[str, Any], timeout: float) -> str | None:
    """统一的 chat/completions POST，失败一律返回 None（不抛出）。"""
    base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    key = os.environ.get("LLM_API_KEY", "")
    if not base:
        return None

    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, IndexError, TimeoutError, OSError, ValueError):
        return None


def complete_vision(
    image_path: str,
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 1200,
    temperature: float = 0.0,
    timeout: float | None = None,
) -> str | None:
    """多模态调用：把图纸图片与提示词一起发给 MaaS，返回文本。

    未配置、图片编码失败或请求失败时返回 None，调用方需自行降级。
    超时可用 ``LLM_VISION_TIMEOUT``（秒）覆盖，默认 90s。
    """
    base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    if not base:
        return None

    try:
        raw, mime = encode_image_for_vision(image_path)
    except Exception:
        return None

    if timeout is None:
        try:
            timeout = float(os.environ.get("LLM_VISION_TIMEOUT") or VISION_TIMEOUT)
        except ValueError:
            timeout = VISION_TIMEOUT

    data_uri = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
    model = os.environ.get("LLM_VISION_MODEL") or os.environ.get("LLM_MODEL", "default")

    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ],
    })

    return _post_chat(
        {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        timeout,
    )


def extract_json(text: str | None) -> Any:
    """从模型回复中稳健地提取 JSON（容忍 ```json 围栏与前后解释文字）。"""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        # 去掉首行围栏与结尾围栏
        s = s.split("\n", 1)[-1] if "\n" in s else s
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    s = s.strip()

    try:
        return json.loads(s)
    except ValueError:
        pass

    # 退一步：截取第一个 '{' 到最后一个 '}'
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(s[start:end + 1])
        except ValueError:
            return None
    return None


def _config() -> tuple[str, str, str]:
    base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "default")
    return base, key, model


def complete(prompt: str, *, system: str | None = None, max_tokens: int = 512) -> str | None:
    """调用 OpenAI 兼容的 chat/completions。未配置或失败时返回 None。"""
    base, _key, model = _config()
    if not base:
        return None

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    return _post_chat(
        {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
        },
        TIMEOUT,
    )


def explain_run(result: dict[str, Any], *, use_llm: bool = True) -> dict[str, Any]:
    """生成"审查—修复"说明。优先用模型，不可用时退化为确定性摘要。"""
    issues = result.get("issues", [])
    fixes = result.get("fixes", [])
    summary = (
        f"共发现 {len(issues)} 个问题，尝试修复 {len(fixes)} 次，"
        f"最终状态 {result.get('state')}，剩余问题 {len(result.get('remaining', []))} 个。"
    )

    # 避免 f-string 同引号嵌套（PEP 701 需 Python≥3.12），改用 str.format
    detail = "; ".join(
        "{}：{}".format(
            f["fix_id"],
            ", ".join("{} {}→{}".format(c["param"], c["old"], c["new"]) for c in f["changes"]),
        )
        for f in fixes
    ) or "无自动修复。"

    text: str | None = None
    if use_llm and llm_available():
        prompt = (
            "你是机械设计审查助手。请用中文简要说明下列问题的成因与修复依据，"
            "并指出仍需人工确认的项。\n"
            f"问题：{json.dumps(issues, ensure_ascii=False)[:2000]}\n"
            f"修复：{json.dumps(fixes, ensure_ascii=False)[:2000]}\n"
        )
        text = complete(prompt, system="你只依据给定证据作答，不得臆测缺失尺寸。")

    return {
        "summary": summary,
        "changes": detail,
        "explanation": text or "（未配置大模型，以下为确定性摘要）",
        "source": "llm" if text else "deterministic",
        "pending_confirmation": result.get("pending_confirmation", []),
    }