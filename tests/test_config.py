from sat_simulation.config import Settings


def test_postgresql_url_selects_asyncpg_driver() -> None:
    settings = Settings(database_url="postgresql://user:secret@localhost/sat_sim")

    assert settings.database_url == "postgresql+asyncpg://user:secret@localhost/sat_sim"


def test_postgres_alias_selects_asyncpg_driver() -> None:
    settings = Settings(database_url="postgres://user:secret@localhost/sat_sim")

    assert settings.database_url == "postgresql+asyncpg://user:secret@localhost/sat_sim"
