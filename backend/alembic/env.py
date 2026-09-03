from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.db.base import Base
from app.modules.geocoding import models as geocoding_models  # noqa: F401 - registra metadata
from app.modules.identity import models as identity_models  # noqa: F401 - registra metadata
from app.modules.imports import models as imports_models  # noqa: F401 - registra metadata
from app.modules.jobs import models as jobs_models  # noqa: F401 - registra metadata
from app.modules.notifications import models as notifications_models  # noqa: F401
from app.modules.planning import models as planning_models  # noqa: F401 - registra metadata
from app.modules.routing import models as routing_models  # noqa: F401 - registra metadata
from app.modules.zoning import models as zoning_models  # noqa: F401 - registra metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    # Ignora tablas de extensiones (PostGIS/tiger geocoder) que no gestionamos con Alembic.
    return not (reflected and compare_to is None)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
