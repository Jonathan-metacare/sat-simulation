from __future__ import annotations

import base64

import httpx
import pytest

from sat_simulation.common.models import ProductLevel, ProductManifest
from sat_simulation.payload.providers import (
    OpenAICompatibleLanguageProvider,
    PlaceholderLanguageProvider,
)


@pytest.mark.asyncio
async def test_placeholders_never_fabricate_model_output(tmp_path) -> None:
    path = tmp_path / "l1b.tif"
    path.write_bytes(b"fixture")
    product = ProductManifest(
        run_id="run",
        mission_id="mission",
        level=ProductLevel.L1B,
        name=path.name,
        mime_type="image/tiff",
        size_bytes=path.stat().st_size,
        sha256="0" * 64,
    )
    language = await PlaceholderLanguageProvider().analyze({}, [product])
    assert language.status == "not_configured"
    assert language.content is None


@pytest.mark.asyncio
async def test_language_provider_sends_l1b_preview_and_user_context(tmp_path, monkeypatch) -> None:
    thumbnail = tmp_path / "l1b.png"
    thumbnail.write_bytes(b"png-preview")
    product = ProductManifest(
        run_id="run",
        mission_id="mission",
        level=ProductLevel.L1B,
        name="l1b.tif",
        mime_type="image/tiff",
        size_bytes=123,
        sha256="1" * 64,
        quality={"truth_rmse": 0.01},
    )
    captured: dict = {}

    async def fake_post(_self, url, **kwargs):
        captured.update({"url": url, **kwargs})
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "model": "vision-test",
                "choices": [{"message": {"content": "发现一艘船。"}, "finish_reason": "stop"}],
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = await OpenAICompatibleLanguageProvider(
        "http://ollama:11434", model="vision-test", timeout=30
    ).analyze(
        {
            "thumbnail_path": str(thumbnail),
            "project_context": "海上监测项目",
            "analysis_prompt": "识别船舶并说明依据",
        },
        [product],
    )

    messages = captured["json"]["messages"]
    user_content = messages[1]["content"]
    assert captured["url"] == "http://ollama:11434/v1/chat/completions"
    assert "海上监测项目" in user_content[0]["text"]
    assert "识别船舶并说明依据" in user_content[0]["text"]
    assert product.sha256 in user_content[0]["text"]
    assert user_content[1]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(b"png-preview").decode("ascii")
    )
    assert result.content == "发现一艘船。"
    assert result.model_version == "vision-test"
    assert result.finish_reason == "stop"
    assert result.truncated is False
