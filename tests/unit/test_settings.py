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


def test_override_url_is_pinned_to_psycopg3():
    """Providers hand out postgres:// or postgresql://; both route to psycopg2 by
    default, which this project does not use."""
    s = Settings(database_url_override="postgres://u:p@host/db?sslmode=require")
    assert s.database_url.startswith("postgresql+psycopg://")
    assert s.database_url.endswith("?sslmode=require")


def test_postgresql_scheme_is_also_pinned():
    s = Settings(database_url_override="postgresql://u:p@host/db")
    assert s.database_url == "postgresql+psycopg://u:p@host/db"


def test_explicit_driver_is_left_alone():
    url = "postgresql+psycopg://u:p@host/db"
    assert Settings(database_url_override=url).database_url == url


def test_override_takes_precedence_over_parts():
    s = Settings(postgres_host="localhost", database_url_override="postgresql://u:p@neon/db")
    assert "neon" in s.database_url


def test_managed_flag_reflects_override():
    assert Settings(database_url_override="postgresql://u:p@h/d").is_managed_database
    assert not Settings().is_managed_database


def test_a_password_with_percent_encoding_survives_alembic():
    """Regression: alembic.ini is parsed by configparser, which reads `%` as
    interpolation syntax and raises before it ever connects.

    Only environments whose password needs URL-encoding are affected, so this passed
    every local run -- the development password is plain -- and failed on the first
    real deploy, where RDS generates a password encoding to `%7B...%3A...%25`.
    """
    import configparser

    from app.core.settings import Settings

    encoded = "postgresql+psycopg://cpi:xSHw%7Bhk%3AFo%25@host:5432/cpi?sslmode=require"
    settings = Settings(_env_file=None, database_url_override=encoded)

    parser = configparser.ConfigParser()
    parser.add_section("alembic")
    # What migrations/env.py does.
    parser.set("alembic", "sqlalchemy.url", settings.alembic_url.replace("%", "%%"))

    assert parser.get("alembic", "sqlalchemy.url") == settings.alembic_url
