"""Caché de geocodificación por hash de dirección normalizada. Ref: 1.BE.9, diseño 7.2/11.5."""
from __future__ import annotations

import hashlib
import json

import redis

CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 días
PROVIDER_VERSION = "nominatim-v2"  # v2: jsonv2 category/type → place_class (caseríos)


class GeocodeCache:
    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    def _key(self, query_hash: str) -> str:
        return f"sofia:geocode-cache:{PROVIDER_VERSION}:{query_hash}"

    @staticmethod
    def hash_query(normalized_address: str, *, postal_code: str, municipality: str) -> str:
        payload = f"{normalized_address.casefold()}|{postal_code}|{municipality.casefold()}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, query_hash: str) -> list[dict] | None:
        raw = self._redis.get(self._key(query_hash))
        return json.loads(raw) if raw else None

    def set(self, query_hash: str, candidates: list[dict]) -> None:
        self._redis.set(self._key(query_hash), json.dumps(candidates), ex=CACHE_TTL_SECONDS)
