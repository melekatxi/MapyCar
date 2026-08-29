"""Configuración de la aplicación vía variables de entorno."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOFIA_", env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+psycopg://sofia:sofia_dev_password@localhost:5432/sofia"
    redis_url: str = "redis://localhost:6379/0"
    nominatim_base_url: str = "http://localhost:8080"
    osrm_base_url: str = "http://localhost:5001"
    field_encryption_active_key_id: str = "k1"
    field_encryption_keys: str = ""  # "k1:base64key,k2:base64key"


@lru_cache
def get_settings() -> Settings:
    return Settings()
