"""Opt-in LangChain Agent for verified mission image analysis.

The Agent deliberately exposes only closures over the current verified GPU job.
It has no arbitrary filesystem, network, shell, or mission-control capability.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from time import monotonic
from typing import Any

import rasterio

from sat_simulation.common.models import AnalysisResult, ProductLevel, ProductManifest

DEFAULT_AGENT_SYSTEM_PROMPT = (
    "你是星载光学遥感图像分析助手。直接输出最终分析，不输出思考过程；"
    "明确区分图像可见事实、结合元数据的推断和不确定性。"
)
ALLOWED_AGENT_TOOLS = frozenset({"mission_context", "verified_products", "l1b_metadata"})


def normalize_agent_configuration(value: Any) -> dict[str, Any]:
    """Drop malformed or unsupported fields received over the GTX wire."""
    raw = value if isinstance(value, dict) else {}
    enabled = raw.get("enabled") is True
    model = str(raw.get("model") or "").strip()[:256]
    prompt = str(raw.get("system_prompt") or DEFAULT_AGENT_SYSTEM_PROMPT).strip()
    selected = raw.get("tools") if isinstance(raw.get("tools"), list) else []
    tools = [item for item in selected if isinstance(item, str) and item in ALLOWED_AGENT_TOOLS]
    return {
        "enabled": enabled,
        "model": model,
        "system_prompt": prompt or DEFAULT_AGENT_SYSTEM_PROMPT,
        "tools": list(dict.fromkeys(tools)),
    }


class LangChainOllamaAgent:
    def __init__(self, url: str, *, model: str, timeout: float, configuration: dict[str, Any]):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.configuration = normalize_agent_configuration(configuration)

    @staticmethod
    def _text(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "\n".join(
                item if isinstance(item, str) else str(item.get("text", ""))
                for item in value
                if isinstance(item, (str, dict))
            ).strip()
        return str(value or "")

    def _tools(
        self,
        *,
        context: dict[str, Any],
        products: list[ProductManifest],
        l1b_path: Path,
    ) -> list[Any]:
        # Imports remain here so Agent-off deployments do not need to import
        # LangChain at runtime and retain the existing provider behavior.
        from langchain_core.tools import tool

        selected = set(self.configuration["tools"])
        tools: list[Any] = []
        if "mission_context" in selected:
            @tool
            def mission_context() -> str:
                """Read the current mission and its requested analysis."""
                allowed = (
                    "mission_id", "mission_name", "target_name", "target_latitude",
                    "target_longitude", "scene_id", "project_context", "analysis_prompt",
                )
                return json.dumps({key: context.get(key) for key in allowed}, ensure_ascii=False)
            tools.append(mission_context)
        if "verified_products" in selected:
            @tool
            def verified_products() -> str:
                """Read verified product manifests and SHA-256 checksums."""
                return json.dumps(
                    [item.model_dump(mode="json") for item in products], ensure_ascii=False
                )
            tools.append(verified_products)
        if "l1b_metadata" in selected:
            @tool
            def l1b_metadata() -> str:
                """Read verified L1B raster metadata and preview availability."""
                with rasterio.open(l1b_path) as dataset:
                    return json.dumps(
                        {
                            "width": dataset.width,
                            "height": dataset.height,
                            "bands": dataset.count,
                            "dtypes": list(dataset.dtypes),
                            "crs": str(dataset.crs) if dataset.crs else None,
                            "transform": list(dataset.transform),
                            "thumbnail_available": Path(str(context["thumbnail_path"])).is_file(),
                        },
                        ensure_ascii=False,
                    )
            tools.append(l1b_metadata)
        return tools

    async def analyze(
        self, context: dict[str, Any], products: list[ProductManifest]
    ) -> AnalysisResult:
        from langchain.agents import create_agent
        from langchain_core.messages import HumanMessage
        from langchain_ollama import ChatOllama

        started = monotonic()
        thumbnail = Path(str(context["thumbnail_path"]))
        l1b = next((item for item in products if item.level == ProductLevel.L1B), None)
        if not l1b:
            raise ValueError("Agent requires a verified L1B product")
        l1b_path = Path(str(l1b.artifact_path))
        if not thumbnail.is_file() or not l1b_path.is_file():
            raise ValueError("Agent requires verified L1B preview and raster artifacts")
        encoded = base64.b64encode(thumbnail.read_bytes()).decode("ascii")
        model = ChatOllama(
            model=self.model,
            base_url=self.url,
            client_kwargs={"timeout": self.timeout},
            async_client_kwargs={"timeout": self.timeout},
        )
        agent = create_agent(
            model,
            tools=self._tools(context=context, products=products, l1b_path=l1b_path),
            system_prompt=self.configuration["system_prompt"],
        )
        request_text = (
            "分析随消息提供的已校验 L1B 光学产品视觉预览。"
            "可按需使用已启用的只读工具来核验任务和产品上下文。\n"
            f"用户分析要求：{context.get('analysis_prompt') or '描述图像中的主要内容。'}"
        )
        response = await agent.ainvoke(
            {"messages": [HumanMessage(content=[
                {"type": "text", "text": request_text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ])]}
        )
        messages = response.get("messages") if isinstance(response, dict) else None
        if not messages:
            raise ValueError("LangChain Agent returned no final message")
        content = self._text(messages[-1].content)
        if not content:
            raise ValueError("LangChain Agent returned an empty final message")
        return AnalysisResult(
            status="ok",
            provenance="model",
            provider="langchain-ollama-agent",
            model_version=self.model,
            elapsed_ms=(monotonic() - started) * 1000,
            content=content,
        )
