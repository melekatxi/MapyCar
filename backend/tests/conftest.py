from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
# PostGIS dedicado a tests. Si está definido, no se arranca testcontainers.
_TEST_DATABASE_ENV = "SOFIA_TEST_DATABASE_URL"
_APP_ROLE = "sofia_app_role"
_APP_ROLE_PASSWORD = "sofia_app_pw"


def has_container_runtime() -> bool:
    return shutil.which("docker") is not None or shutil.which("podman") is not None


def _prepare_postgis(superuser_url: str) -> str:
    bootstrap_engine = create_engine(superuser_url)
    with bootstrap_engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    bootstrap_engine.dispose()

    env = os.environ.copy()
    env["SOFIA_DATABASE_URL"] = superuser_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
    )

    # El superusuario ignora RLS (incluso con FORCE). El rol de aplicación no.
    app_role_engine = create_engine(superuser_url)
    with app_role_engine.begin() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN "
                f"IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_APP_ROLE}') THEN "
                f"EXECUTE 'DROP OWNED BY {_APP_ROLE} CASCADE'; "
                "END IF; END $$;"
            )
        )
        conn.execute(text(f"DROP ROLE IF EXISTS {_APP_ROLE}"))
        conn.execute(
            text(
                f"CREATE ROLE {_APP_ROLE} LOGIN PASSWORD '{_APP_ROLE_PASSWORD}' "
                "NOSUPERUSER NOBYPASSRLS"
            )
        )
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE}"))
        conn.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
                f"TO {_APP_ROLE}"
            )
        )
        conn.execute(
            text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {_APP_ROLE}"
            )
        )
    app_role_engine.dispose()

    parsed = urlsplit(superuser_url)
    return urlunsplit(
        parsed._replace(netloc=f"{_APP_ROLE}:{_APP_ROLE_PASSWORD}@{parsed.hostname}:{parsed.port}")
    )


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    external = os.environ.get(_TEST_DATABASE_ENV, "").strip()
    if external:
        yield _prepare_postgis(external)
        return
    if not has_container_runtime():
        pytest.skip(
            "Los tests de BD necesitan PostGIS. Arranca Docker/Podman o define "
            f"{_TEST_DATABASE_ENV}=postgresql+psycopg://user:pass@host:5432/sofia_test "
            "(base dedicada, con permiso para CREATE EXTENSION/ROLE)."
        )
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgis/postgis:17-3.4", driver="psycopg") as postgres:
        yield _prepare_postgis(postgres.get_connection_url())


@pytest.fixture()
def db_session(postgres_url: str) -> Iterator[Session]:
    engine = create_engine(postgres_url)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
