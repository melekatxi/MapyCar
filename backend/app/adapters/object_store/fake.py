from __future__ import annotations

from app.adapters.object_store.interface import ObjectStore


class InMemoryObjectStore(ObjectStore):
    """Doble de prueba en memoria. Producción usa almacenamiento S3-compatible cifrado."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, *, key: str, content: bytes, content_type: str) -> None:
        self._objects[key] = content

    def get(self, *, key: str) -> bytes:
        return self._objects[key]
