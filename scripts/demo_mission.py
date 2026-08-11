from __future__ import annotations

import asyncio
import json

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
        mission_id = response.json()["mission_id"]
        while True:
            detail = (await client.get(f"/api/missions/{mission_id}")).json()
            print(
                json.dumps(
                    {"mission_id": mission_id, "status": detail["status"]},
                    ensure_ascii=False,
                )
            )
            if detail["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
