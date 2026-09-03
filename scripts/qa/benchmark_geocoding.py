"""Benchmark de geocodificación contra Nominatim autoalojado. Ref: RNF-01, 1.BE.14.

Usa el pipeline real (normalización + scoring, sin caché para medir el caso peor)
sobre el dataset ficticio de Bizkaia. El fixture tiene 120 filas; se proyecta
linealmente el tiempo para un lote de 200 (criterio de aceptación de RNF-01).
"""
from __future__ import annotations

import asyncio
import csv
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.adapters.geocoder.nominatim import NominatimGeocoder  # noqa: E402
from app.modules.geocoding.normalization import normalize_for_geocoding, strip_floor_door  # noqa: E402
from app.modules.geocoding.overlay import apply_overlay  # noqa: E402
from app.modules.geocoding.scoring import classify, score_candidate  # noqa: E402

SOURCE_CSV = REPO_ROOT / "docs" / "requisitos" / "direcciones-ejemplo-bizkaia.csv"
NOMINATIM_URL = "http://localhost:8080"
TARGET_BATCH_SIZE = 200


async def main() -> None:
    with SOURCE_CSV.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))

    geocoder = NominatimGeocoder(NOMINATIM_URL, bounding_box=(-3.6, 42.85, -1.9, 43.55))
    outcomes = {"matched": 0, "ambiguous": 0, "not_found": 0}

    start = time.perf_counter()
    for row in rows:
        normalized = normalize_for_geocoding(strip_floor_door(row["direccion"]))
        candidates = await geocoder.geocode(
            address_text=normalized, postal_code=row["codigo_postal"], municipality=row["municipio"]
        )
        candidates = apply_overlay(
            candidates,
            address_text=normalized,
            postal_code=row["codigo_postal"],
            municipality=row["municipio"],
        )
        scored = [(c, score_candidate(c, postal_code=row["codigo_postal"], municipality=row["municipio"])) for c in candidates]
        outcomes[classify(scored)] += 1
    elapsed = time.perf_counter() - start

    rate = len(rows) / elapsed
    projected_200 = TARGET_BATCH_SIZE / rate

    print(f"Direcciones procesadas: {len(rows)}")
    print(f"Tiempo total: {elapsed:.2f} s ({rate:.2f} direcciones/s)")
    print(f"Proyección para {TARGET_BATCH_SIZE} direcciones: {projected_200:.2f} s ({projected_200 / 60:.2f} min)")
    print(f"Resultados: {outcomes}")


if __name__ == "__main__":
    asyncio.run(main())
