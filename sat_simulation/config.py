from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SAT_SIM_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./runtime-data/sat-simulation.db"
    data_dir: Path = Path("runtime-data")
    host: str = "0.0.0.0"
    ground_api_port: int = 8000
    platform_api_port: int = 8001
    gpu_api_port: int = 8002
    optical_api_port: int = 8003
    ground_downlink_host: str = "127.0.0.1"
    ground_downlink_port: int = 9201
    platform_uplink_host: str = "127.0.0.1"
    platform_uplink_port: int = 9200
    gpu_gtx_host: str = "127.0.0.1"
    gpu_gtx_port: int = 9101
    platform_gtx_result_host: str = "127.0.0.1"
    platform_gtx_result_bind_host: str | None = None
    platform_gtx_result_advertise_host: str = "127.0.0.1"
    platform_gtx_result_port: int = 9102
    optical_payload_host: str = "127.0.0.1"
    optical_payload_port: int = 9300
    platform_payload_result_host: str = "127.0.0.1"
    platform_payload_result_port: int = 9301
    platform_http_url: str = "http://127.0.0.1:8001"
    gpu_http_url: str = "http://127.0.0.1:8002"
    ground_http_url: str = "http://127.0.0.1:8000"
    optical_http_url: str = "http://127.0.0.1:8003"
    oci_runtime: str = "docker"
    processor_image: str = "spacezenith/processor-python:3.12"
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    yolo_api_url: str | None = None
    yolo_model: str = "default"
    yolo_api_key: str | None = None
    llm_api_url: str | None = None
    llm_model: str = "gpt-4.1-mini"
    llm_api_key: str | None = None
    llm_require_vision: bool = False
    provider_timeout_seconds: float = 80
    stage_animation_seconds: float = 8.0

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]


settings = Settings()
