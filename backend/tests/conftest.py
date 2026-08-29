from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgis/postgis:17-3.4", driver="psycopg") as postgres:
        superuser_url = postgres.get_connection_url()
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

        # El usuario por defecto del contenedor es superusuario y por tanto ignora RLS
        # (incluso con FORCE). Se crea un rol de aplicación sin privilegios especiales
        # para que las pruebas de RLS reflejen el comportamiento real en producción.
        app_role_engine = create_engine(superuser_url)
        with app_role_engine.begin() as conn:
            conn.execute(text("DROP ROLE IF EXISTS sofia_app_role"))
            conn.execute(
                text("CREATE ROLE sofia_app_role LOGIN PASSWORD 'sofia_app_pw' NOSUPERUSER NOBYPASSRLS")
            )
            conn.execute(text("GRANT USAGE ON SCHEMA public TO sofia_app_role"))
            conn.execute(
                text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sofia_app_role")
            )
        app_role_engine.dispose()

        parsed = urlsplit(superuser_url)
        app_role_url = urlunsplit(
            parsed._replace(netloc=f"sofia_app_role:sofia_app_pw@{parsed.hostname}:{parsed.port}")
        )
        yield app_role_url


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
