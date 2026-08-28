from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from time import monotonic
from typing import Any, Protocol

import httpx

from sat_simulation.common.models import (
    AnalysisResult,
    Detection,
    DetectionResult,
    ProductManifest,
)


class DetectionProvider(Protocol):
    async def detect(
        self,
        product: ProductManifest,
        path: Path,
        options: dict[str, Any] | None = None,
    ) -> DetectionResult: ...


class LanguageProvider(Protocol):
    async def analyze(
        self,
        context: dict[str, Any],
        products: list[ProductManifest],
    ) -> AnalysisResult: ...


class PlaceholderDetectionProvider:
    async def detect(
        self,
        product: ProductManifest,
        path: Path,
        options: dict[str, Any] | None = None,
    ) -> DetectionResult:
        return DetectionResult(
            status="not_configured",
            provenance="placeholder",
            provider="placeholder-detection-provider",
            reason="本地 YOLO 服务尚未配置；未生成任何模拟检测目标。",
        )


class PlaceholderLanguageProvider:
    async def analyze(
        self,
        context: dict[str, Any],
        products: list[ProductManifest],
    ) -> AnalysisResult:
        return AnalysisResult(
            status="not_configured",
            provenance="placeholder",
            provider="placeholder-language-provider",
            reason="本地 LLM 服务尚未配置。",
        )


class YOLOHTTPProvider:
    def __init__(self, url: str, *, model: str, timeout: float, api_key: str | None = None):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key

    async def detect(
        self,
        product: ProductManifest,
        path: Path,
        options: dict[str, Any] | None = None,
    ) -> DetectionResult:
        started = monotonic()
        options = options or {}
        thumbnail = Path(str(options.get("thumbnail_path", path)))
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        image_content, preview_content = await asyncio.gather(
            asyncio.to_thread(path.read_bytes),
            asyncio.to_thread(thumbnail.read_bytes),
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.url}/detect",
                headers=headers,
                files={
                    "l1b": (path.name, image_content, "image/tiff"),
                    "thumbnail": (thumbnail.name, preview_content, "image/png"),
                },
                data={
                    "options": json.dumps(options.get("provider_options", {})),
                    "model": self.model,
                },
            )
            response.raise_for_status()
        body = response.json()
        detections: list[Detection] = []
        for item in body.get("detections", []):
            label = str(item.get("label", "")).lower()
            if label not in {"ship", "aircraft", "vehicle"}:
                continue
            bbox = item.get("bbox_pixel") or item.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            detections.append(
                Detection(
                    label=label,
                    confidence=float(item.get("confidence", 0)),
                    bbox_pixel=tuple(float(value) for value in bbox),
                    polygon_wgs84=item.get("polygon_wgs84"),
                )
            )
        return DetectionResult(
            status="ok",
            provenance="model",
            provider="yolo-http",
            model_version=str(body.get("model_version") or self.model),
            elapsed_ms=(monotonic() - started) * 1000,
            detections=detections,
        )


class OpenAICompatibleLanguageProvider:
    def __init__(self, url: str, *, model: str, timeout: float, api_key: str | None = None):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key

    async def analyze(
        self,
        context: dict[str, Any],
        products: list[ProductManifest],
    ) -> AnalysisResult:
        started = monotonic()
        context_data = dict(context)
        thumbnail = Path(str(context_data.pop("thumbnail_path")))
        encoded = base64.b64encode(thumbnail.read_bytes()).decode("ascii")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是星载光学遥感图像分析助手。直接输出最终分析，不输出思考过程；"
                        "明确区分图像可见事实、结合元数据的推断和不确定性。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "分析随消息提供的 L1B 光学产品视觉预览。原始 L1B 是 "
                                "GeoTIFF，预览由 GPU 从已校验的 L1B 生成。"
                            )
                            + "\n用户分析要求："
                            + str(context_data.get("analysis_prompt") or "描述图像中的主要内容。")
                            + "\n任务、项目背景与 L1B 元数据："
                            + json.dumps(
                                {
                                    "context": context_data,
                                    "products": [item.model_dump(mode="json") for item in products],
                                },
                                ensure_ascii=False,
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{encoded}"},
                        },
                    ],
                },
            ],
            "max_tokens": 4096,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.url}/v1/chat/completions", headers=headers, json=payload
            )
            response.raise_for_status()
        body = response.json()
        choice = body["choices"][0]
        content = choice["message"]["content"]
        finish_reason = str(choice.get("finish_reason") or "") or None
        return AnalysisResult(
            status="ok",
            provenance="model",
            provider="openai-compatible",
            model_version=str(body.get("model") or self.model),
            elapsed_ms=(monotonic() - started) * 1000,
            content=str(content),
            finish_reason=finish_reason,
            truncated=finish_reason == "length",
            reason="模型输出达到长度上限，报告可能不完整" if finish_reason == "length" else None,
        )
