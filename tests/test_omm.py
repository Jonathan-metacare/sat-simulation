from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sgp4.api import Satrec

from sat_simulation.config import Settings
from sat_simulation.omm import extract_omm, omm_hash, omm_to_tle
from sat_simulation.services.ground import GroundState


def valid_omm() -> dict[str, str]:
    return {
        "NORAD_CAT_ID": "25544", "OBJECT_NAME": "ISS (ZARYA)", "OBJECT_ID": "1998-067A",
        "EPOCH": "2024-06-01T12:00:00.000000Z", "MEAN_MOTION": "15.50000000",
        "ECCENTRICITY": "0.0005000", "INCLINATION": "51.6400", "RA_OF_ASC_NODE": "150.0000",
        "ARG_OF_PERICENTER": "50.0000", "MEAN_ANOMALY": "310.0000", "EPHEMERIS_TYPE": "0",
        "CLASSIFICATION_TYPE": "U", "ELEMENT_SET_NO": "999", "REV_AT_EPOCH": "45000",
        "BSTAR": "0.00012345", "MEAN_MOTION_DOT": "0.0001", "MEAN_MOTION_DDOT": "0.0",
    }


def test_omm_exports_valid_tle() -> None:
    omm = extract_omm(valid_omm(), 25544)
    line1, line2 = omm_to_tle(omm)
    assert len(line1) == len(line2) == 69
    assert line1.startswith("1 25544") and line2.startswith("2 25544")
    assert Satrec.twoline2rv(line1, line2).error == 0


def test_omm_rejects_missing_required_data() -> None:
    payload = valid_omm()
    del payload["OBJECT_ID"]
    with pytest.raises(ValueError, match="OBJECT_ID"):
        extract_omm(payload, 25544)


@pytest.mark.asyncio
async def test_norad_lookup_persists_only_latest_omm(tmp_path, monkeypatch) -> None:
    app_settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'omm.db'}", data_dir=tmp_path,
        keeptrack_api_key="secret",
    )
    state = GroundState(app_settings)
    await state.repo.init()

    async def fake_get(_self, url, **kwargs):
        assert url.endswith("/25544/omm")
        assert kwargs["headers"] == {"X-API-Key": "secret"}
        return httpx.Response(200, request=httpx.Request("GET", url), json=valid_omm())

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await state.lookup_norad(25544)
    cached = await state.repo.cached_latest_satellite_omm()
    assert result["satellite_name"] == "ISS (ZARYA)"
    assert len(cached) == 1
    assert cached[0]["norad_id"] == 25544
    assert cached[0]["content_hash"] == omm_hash(extract_omm(valid_omm(), 25544))
    await state.repo.close()


@pytest.mark.asyncio
async def test_background_refresh_skips_records_checked_today(tmp_path, monkeypatch) -> None:
    state = GroundState(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'omm.db'}", data_dir=tmp_path,
        keeptrack_api_key="secret",
    ))
    await state.repo.init()
    omm = extract_omm(valid_omm(), 25544)
    line1, line2 = omm_to_tle(omm)
    await state.repo.upsert_latest_satellite_omm(
        norad_id=25544, satellite_name=omm["OBJECT_NAME"], omm_epoch=omm["EPOCH"], omm=omm,
        tle_line1=line1, tle_line2=line2, content_hash=omm_hash(omm), checked_at=datetime.now(UTC),
    )
    calls: list[int] = []

    async def fake_lookup(norad_id: int):
        calls.append(norad_id)

    monkeypatch.setattr(state, "lookup_norad", fake_lookup)
    await state.refresh_stale_omm_cache()
    assert calls == []
    await state.repo.close()
