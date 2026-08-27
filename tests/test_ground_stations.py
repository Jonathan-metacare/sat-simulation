from __future__ import annotations

import httpx
import pytest

from sat_simulation.config import Settings
from sat_simulation.ground_stations import normalize_satnogs_station
from sat_simulation.services.ground import GroundState


def station(station_id: int, name: str) -> dict[str, object]:
    return {
        "id": station_id,
        "name": name,
        "lat": 39.9042,
        "lng": 116.4074,
        "altitude": "50",
        "min_horizon": "10",
        "status": "Online",
        "created": "2024-01-01T00:00:00Z",
        "last_seen": "2024-01-02T00:00:00Z",
    }


def test_normalize_satnogs_station() -> None:
    result = normalize_satnogs_station(station(42, "Beijing Test"))
    assert result["station_id"] == 42
    assert result["altitude_m"] == 50.0
    assert result["longitude"] == 116.4074


@pytest.mark.asyncio
async def test_import_station_catalog_once_and_search_locally(tmp_path, monkeypatch) -> None:
    state = GroundState(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'stations.db'}", data_dir=tmp_path,
        satnogs_station_api_url="https://stations.example/api/stations/",
    ))
    await state.repo.init()
    requests: list[str] = []

    async def fake_get(_self, url, **_kwargs):
        requests.append(url)
        if url.endswith("page=2"):
            body = {"results": [station(2, "Shanghai Station")], "next": None}
        else:
            body = {"results": [station(1, "Beijing Station")], "next": "?page=2"}
        return httpx.Response(200, request=httpx.Request("GET", url), json=body)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    await state.import_satnogs_ground_stations()
    assert await state.repo.catalog_status("satnogs_ground_stations_v1") == "complete"
    assert len(requests) == 2
    result = await state.search_ground_stations("BEIJ")
    assert result["status"] == "ready"
    assert result["results"][0]["name"] == "Beijing Station"

    await state.import_satnogs_ground_stations()
    assert len(requests) == 2
    await state.repo.close()


@pytest.mark.asyncio
async def test_import_accepts_unpaginated_station_list(tmp_path, monkeypatch) -> None:
    state = GroundState(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'stations.db'}", data_dir=tmp_path,
        satnogs_station_api_url="https://stations.example/api/stations/",
    ))
    await state.repo.init()

    async def fake_get(_self, url, **_kwargs):
        return httpx.Response(200, request=httpx.Request("GET", url), json=[station(7, "Array Station")])

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    await state.import_satnogs_ground_stations()
    assert await state.repo.catalog_status("satnogs_ground_stations_v1") == "complete"
    assert (await state.search_ground_stations("array"))["results"][0]["station_id"] == 7
    await state.repo.close()


@pytest.mark.asyncio
async def test_search_reports_initializing_before_catalog_is_ready(tmp_path) -> None:
    state = GroundState(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'stations.db'}", data_dir=tmp_path,
    ))
    await state.repo.init()
    assert await state.search_ground_stations("beijing") == {"status": "initializing", "results": []}
    await state.repo.close()


@pytest.mark.asyncio
async def test_clear_catalog_caches_preserves_other_database_data(tmp_path) -> None:
    state = GroundState(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'stations.db'}", data_dir=tmp_path,
    ))
    await state.repo.init()
    await state.repo.upsert_satnogs_ground_stations([normalize_satnogs_station(station(3, "Cached Station"))])
    await state.repo.set_catalog_status("satnogs_ground_stations_v1", "complete")
    await state.repo.upsert_latest_satellite_omm(
        norad_id=25544, satellite_name="ISS", omm_epoch="2026-01-01T00:00:00Z",
        omm={"OBJECT_NAME": "ISS"}, tle_line1="1" * 69, tle_line2="2" * 69,
        content_hash="a" * 64,
    )

    await state.repo.clear_catalog_caches("satnogs_ground_stations_v1")

    assert await state.repo.cached_latest_satellite_omm() == []
    assert await state.repo.catalog_status("satnogs_ground_stations_v1") is None
    assert await state.repo.search_satnogs_ground_stations("cached") == []
    await state.repo.close()
