"""Puerto ObjectStore. Ref: ADR-06. Almacenamiento propio para ficheros y exportaciones."""
from __future__ import annotations

from abc import ABC, abstractmethod


class ObjectStore(ABC):
    @abstractmethod
    def put(self, *, key: str, content: bytes, content_type: str) -> None:
        """Guarda un objeto (fichero original, export PDF/PNG, etc.)."""

    @abstractmethod
    def get(self, *, key: str) -> bytes:
        """Recupera un objeto por clave."""
