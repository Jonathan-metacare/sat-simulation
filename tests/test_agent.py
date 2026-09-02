from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio

from sat_simulation.common.models import ProductLevel, ProductManifest
from sat_simulation.config import Settings
from sat_simulation.payload.agent import (
    ALLOWED_AGENT_TOOLS,
    DEFAULT_AGENT_SYSTEM_PROMPT,
    LangChainOllamaAgent,
    normalize_agent_configuration,
)


def make_l1b(tmp_path: Path) -> ProductManifest:
    path = tmp_path / "l1b.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=2,
        height=3,
        count=1,
        dtype="uint16",
        crs="EPSG:4326",
    ) as dataset:
        dataset.write(np.ones((1, 3, 2), dtype=np.uint16))
    return ProductManifest(
        run_id="run",
        mission_id="mission",
        level=ProductLevel.L1B,
        name=path.name,
        mime_type="image/tiff",
        size_bytes=path.stat().st_size,
        sha256="a" * 64,
        artifact_path=str(path),
    )


def test_agent_configuration_is_opt_in_and_drops_unknown_tools() -> None:
    value = normalize_agent_configuration(
        {
            "enabled": True,
            "model": "vision-test",
            "system_prompt": "  Inspect this mission carefully. ",
            "tools": ["mission_context", "unknown", "mission_context", "l1b_metadata"],
        }
    )

    assert value == {
        "enabled": True,
        "model": "vision-test",
        "system_prompt": "Inspect this mission carefully.",
        "tools": ["mission_context", "l1b_metadata"],
    }


def test_agent_configuration_defaults_to_disabled_safe_prompt() -> None:
    value = normalize_agent_configuration({"enabled": "true", "system_prompt": "", "tools": "all"})

    assert value["enabled"] is False
    assert value["model"] == ""
    assert value["system_prompt"] == DEFAULT_AGENT_SYSTEM_PROMPT
    assert value["tools"] == []
    assert ALLOWED_AGENT_TOOLS == {"mission_context", "verified_products", "l1b_metadata"}


def test_settings_exposes_sanitized_agent_configuration() -> None:
    config = Settings(
        agent_enabled=True,
        agent_model="agent-vision",
        agent_system_prompt="  Verify the scene. ",
        agent_tools='["verified_products", "unknown"]',
    ).agent_configuration

    assert config == {
        "enabled": True,
        "model": "agent-vision",
        "system_prompt": "Verify the scene.",
        "tools": ["verified_products"],
    }


def test_agent_tools_expose_only_current_verified_context(tmp_path) -> None:
    preview = tmp_path / "preview.png"
    preview.write_bytes(b"preview")
    product = make_l1b(tmp_path)
    agent = LangChainOllamaAgent(
        "http://ollama:11434",
        model="vision-test",
        timeout=30,
        configuration={"enabled": True, "tools": list(ALLOWED_AGENT_TOOLS)},
    )
    tools = {tool.name: tool for tool in agent._tools(
        context={
            "thumbnail_path": str(preview),
            "mission_id": "mission",
            "project_context": "verified project",
            "secret": "must-not-leak",
        },
        products=[product],
        l1b_path=tmp_path / "l1b.tif",
    )}

    context = json.loads(tools["mission_context"].invoke({}))
    manifests = json.loads(tools["verified_products"].invoke({}))
    metadata = json.loads(tools["l1b_metadata"].invoke({}))

    assert context["mission_id"] == "mission"
    assert "secret" not in context
    assert manifests[0]["sha256"] == product.sha256
    assert metadata["thumbnail_available"] is True
    assert metadata["width"] == 2


@pytest.mark.asyncio
async def test_agent_constructs_langchain_ollama_with_configured_timeout(tmp_path, monkeypatch) -> None:
    preview = tmp_path / "preview.png"
    preview.write_bytes(b"preview")
    product = make_l1b(tmp_path)
    captured: dict[str, object] = {}

    class FakeChatOllama:
        def __init__(self, **kwargs):
            captured["model"] = kwargs

    class FakeAgent:
        async def ainvoke(self, request):
            captured["request"] = request
            return {"messages": [type("Message", (), {"content": "verified result"})()]}

    def fake_create_agent(model, *, tools, system_prompt):
        captured.update({"agent_model": model, "tools": tools, "system_prompt": system_prompt})
        return FakeAgent()

    monkeypatch.setattr("langchain_ollama.ChatOllama", FakeChatOllama)
    monkeypatch.setattr("langchain.agents.create_agent", fake_create_agent)
    result = await LangChainOllamaAgent(
        "http://ollama:11434",
        model="vision-test",
        timeout=42,
        configuration={
            "enabled": True,
            "system_prompt": "Use verified facts.",
            "tools": ["mission_context"],
        },
    ).analyze({"thumbnail_path": str(preview), "analysis_prompt": "inspect"}, [product])

    assert captured["model"] == {
        "model": "vision-test",
        "base_url": "http://ollama:11434",
        "client_kwargs": {"timeout": 42},
        "async_client_kwargs": {"timeout": 42},
    }
    assert captured["system_prompt"] == "Use verified facts."
    assert [tool.name for tool in captured["tools"]] == ["mission_context"]
    assert result.provider == "langchain-ollama-agent"
    assert result.content == "verified result"
