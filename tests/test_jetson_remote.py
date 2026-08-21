from __future__ import annotations

from pathlib import Path

import pytest

from sat_simulation.config import Settings
from sat_simulation.services.gpu import GPUState


def test_gpu_reply_endpoint_uses_per_job_callback(tmp_path: Path) -> None:
    state = GPUState(Settings(data_dir=tmp_path))
    assert state.reply_endpoint({"gpu_reply": {"host": "192.168.20.10", "port": 9102}}) == (
        "192.168.20.10",
        9102,
    )


def test_gpu_reply_endpoint_rejects_invalid_port(tmp_path: Path) -> None:
    state = GPUState(Settings(data_dir=tmp_path))
    with pytest.raises(ValueError, match="reply endpoint"):
        state.reply_endpoint({"gpu_reply": {"host": "192.168.20.10", "port": 70000}})


def test_remote_settings_expose_lan_listener_fields() -> None:
    config = Settings(
        platform_gtx_result_bind_host="0.0.0.0",
        platform_gtx_result_advertise_host="192.168.20.10",
    )
    assert config.platform_gtx_result_bind_host == "0.0.0.0"
    assert config.platform_gtx_result_advertise_host == "192.168.20.10"
