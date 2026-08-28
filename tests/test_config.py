from sat_simulation.config import Settings


def test_desktop_defaults_to_local_sqlite() -> None:
    settings = Settings()

    assert settings.database_url == "sqlite+aiosqlite:///./runtime-data/sat-simulation.db"
