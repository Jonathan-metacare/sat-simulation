from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SAT_SIM_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./runtime-data/sat-simulation.db"
    data_dir: Path = Path("runtime-data")
    host: str = "0.0.0.0"
    ground_api_port: int = 8000
    platform_api_port: int = 8001
    gpu_api_port: int = 8002
    ground_downlink_host: str = "127.0.0.1"
    ground_downlink_port: int = 9201
    platform_uplink_host: str = "127.0.0.1"
    platform_uplink_port: int = 9200
    gpu_gtx_host: str = "127.0.0.1"
    gpu_gtx_port: int = 9101
    platform_http_url: str = "http://127.0.0.1:8001"
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    yolo_api_url: str | None = None
    llm_api_url: str | None = None
    provider_timeout_seconds: float = 30

    @field_validator("database_url", mode="before")
    @classmethod
    def use_async_database_driver(cls, value: object) -> object:
        """Accept common PostgreSQL URLs while keeping the service fully async."""
        if not isinstance(value, str):
            return value
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]


settings = Settings()
