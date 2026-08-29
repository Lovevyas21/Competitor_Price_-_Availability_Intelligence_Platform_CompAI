from app.core.settings import Settings


def test_database_url_composes_from_parts():
    s = Settings(
        postgres_user="u",
        postgres_password="p",
        postgres_host="h",
        postgres_port=5433,
        postgres_db="d",
    )
    assert s.database_url == "postgresql+psycopg://u:p@h:5433/d"


def test_bronze_defaults_to_local_backend():
    assert Settings().bronze_backend == "local"
