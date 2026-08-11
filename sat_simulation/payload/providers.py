from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from sat_simulation.common.models import AnalysisResult, DetectionResult, ProductManifest


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
