"""Valida 1.BE.10 contra el ground truth aprobado (0.QA.2): ≥95% `matched` en filas
bien formateadas (excluye las 2 filas rurales intencionadamente ficticias)."""
from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.adapters.geocoder.nominatim import NominatimGeocoder  # noqa: E402
from app.modules.geocoding.normalization import normalize_for_geocoding, strip_floor_door  # noqa: E402
from app.modules.geocoding.overlay import apply_overlay  # noqa: E402
from app.modules.geocoding.scoring import classify, score_candidate  # noqa: E402

SOURCE_CSV = REPO_ROOT / "docs" / "requisitos" / "direcciones-ejemplo-bizkaia.csv"
INTENTIONALLY_FICTIONAL = {"PAC-051", "PAC-058"}
SAMPLE_IDS = [
    "PAC-001", "PAC-002", "PAC-003", "PAC-004", "PAC-005", "PAC-006", "PAC-007", "PAC-008",
    "PAC-009", "PAC-010", "PAC-011", "PAC-012", "PAC-013", "PAC-014", "PAC-015",
    "PAC-034", "PAC-037", "PAC-043", "PAC-044", "PAC-045", "PAC-046", "PAC-047", "PAC-048",
    "PAC-051", "PAC-052", "PAC-053", "PAC-054", "PAC-055", "PAC-058", "PAC-060",
]


async def main() -> None:
    with SOURCE_CSV.open(encoding="utf-8", newline="") as fh:
        rows = {row["id_paciente"]: row for row in csv.DictReader(fh, delimiter=";")}

    geocoder = NominatimGeocoder("http://localhost:8080", bounding_box=(-3.6, 42.85, -1.9, 43.55))
    well_formatted = [pid for pid in SAMPLE_IDS if pid not in INTENTIONALLY_FICTIONAL]
    matched = 0
    for pid in well_formatted:
        row = rows[pid]
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
        outcome = classify(scored)
        if outcome != "matched":
            print(f"NO matched: {pid} ({row['direccion']}) -> {outcome}")
        else:
            matched += 1

    rate = matched / len(well_formatted) * 100
    print(f"\nmatched: {matched}/{len(well_formatted)} ({rate:.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())
