"""Puerto Router. Ref: ADR-06, ADR-10."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Coordinate:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class DistanceMatrix:
    durations_seconds: list[list[float]]
    distances_meters: list[list[float]]


class Router(ABC):
    @abstractmethod
    async def table(self, coordinates: list[Coordinate]) -> DistanceMatrix:
        """Matriz NxN de tiempos/distancias, incluyendo origen y retorno."""

    @abstractmethod
    async def route(self, coordinates: list[Coordinate]) -> dict:
        """Geometría y métricas de la ruta ordenada final."""
