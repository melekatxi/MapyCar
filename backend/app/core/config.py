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
    osrm_profile: str = "driving"
    osrm_dataset_version: str = "dev"
    field_encryption_active_key_id: str = "k1"
    field_encryption_keys: str = ""  # "k1:base64key,k2:base64key"
    s3_endpoint_url: str = ""  # vacío → InMemoryObjectStore (tests sin MinIO)
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "sofia"
    s3_region: str = "us-east-1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
