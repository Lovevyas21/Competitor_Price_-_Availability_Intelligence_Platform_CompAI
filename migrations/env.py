from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.settings import get_settings

config = context.config
# `%` doubled because alembic.ini is read by configparser, which treats a bare `%` as
# interpolation syntax and raises on the URL rather than connecting with it. A password
# containing characters that need URL-encoding therefore breaks migrations -- and only
# in the environment that has one. The local development password is plain, so this
# surfaced for the first time against RDS, whose generated password encodes to
# `%7B...%3A...%25`.
config.set_main_option("sqlalchemy.url", get_settings().alembic_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Raw-SQL migrations for now; no autogenerate target.
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
