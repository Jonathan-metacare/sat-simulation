from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx


async def main() -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=30) as client:
        scenarios = (await client.get("/api/scenarios")).json()
        if not scenarios:
            response = await client.post(
                "/api/scenarios",
                json={"name": "北京光学任务演示", "clock_rate": 100},
            )
            response.raise_for_status()
            scenario = response.json()
        else:
            scenario = scenarios[0]
        response = await client.post(
            "/api/missions",
            json={"scenario_id": scenario["config"]["id"]},
        )
        response.raise_for_status()
        mission_id = response.json()["command"]["id"]
        while True:
            detail = (await client.get(f"/api/missions/{mission_id}")).json()
            print(
                json.dumps(
                    {
                        "mission_id": mission_id,
                        "phase": detail["phase"],
                        "execution_state": detail["execution_state"],
                    },
                    ensure_ascii=False,
                )
            )
            if detail["phase"] == "completed":
                break
            if detail["execution_state"] == "blocked":
                raise SystemExit(detail["block_reason"])
            if detail["execution_state"] in {"waiting", "retryable_error"}:
                advance = await client.post(
                    f"/api/missions/{mission_id}/advance",
                    json={
                        "playback_speed": 5,
                        "idempotency_key": f"demo-{detail['phase']}-{uuid4().hex}",
                    },
                )
                advance.raise_for_status()
            await asyncio.sleep(0.8)


if __name__ == "__main__":
    asyncio.run(main())
