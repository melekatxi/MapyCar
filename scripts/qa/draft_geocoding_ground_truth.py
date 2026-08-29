"""Genera un BORRADOR de verdad de referencia de geocodificación (0.QA.2).

Consulta la instancia pública de Nominatim (uso de desarrollo, bajo volumen, respetando
1 req/s y un User-Agent identificable) para una muestra de 30 direcciones ficticias del
dataset de Bizkaia. El resultado es un borrador: requiere revisión y aprobación manual
antes de usarse como ground truth (criterio de 0.QA.2).
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_CSV = REPO_ROOT / "docs" / "requisitos" / "direcciones-ejemplo-bizkaia.csv"
OUTPUT_MD = REPO_ROOT / "docs" / "requisitos" / "ground-truth-geocoding-draft.md"
USER_AGENT = "sofia-app-dev/0.1 (uso manual de bajo volumen, contacto: soporte@sofia.example)"
SAMPLE_SIZE = 30


def load_sample() -> list[dict[str, str]]:
    with SOURCE_CSV.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    urban = [r for r in rows if r["tipo_zona"] == "Urbana"][:15]
    rural = [r for r in rows if r["tipo_zona"] == "Rural"][:15]
    return urban + rural


def geocode(row: dict[str, str], client: httpx.Client) -> dict:
    query = f"{row['direccion']}, {row['codigo_postal']} {row['municipio']}, {row['provincia']}, España"
    response = client.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=15.0,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        return {"lat": None, "lon": None, "display_name": None}
    top = results[0]
    return {"lat": top["lat"], "lon": top["lon"], "display_name": top["display_name"]}


def main() -> None:
    sample = load_sample()[:SAMPLE_SIZE]
    lines = [
        "# Borrador de verdad de referencia de geocodificación (0.QA.2)",
        "",
        "> **Estado: BORRADOR generado automáticamente contra Nominatim público.**",
        "> Pendiente de revisión y aprobación manual por una persona antes de usarse",
        "> como ground truth para medir el criterio de aceptación RF-05 (≥95% `matched`).",
        "",
        "| ID | Dirección | CP | Municipio | Tipo | Lat (borrador) | Lon (borrador) | Resultado Nominatim |",
        "|---|---|---|---|---|---|---|---|",
    ]
    with httpx.Client() as client:
        for row in sample:
            result = geocode(row, client)
            lines.append(
                f"| {row['id_paciente']} | {row['direccion']} | {row['codigo_postal']} | "
                f"{row['municipio']} | {row['tipo_zona']} | {result['lat'] or '—'} | "
                f"{result['lon'] or '—'} | {result['display_name'] or 'NOT_FOUND'} |"
            )
            time.sleep(1.0)  # política de uso de Nominatim público: máximo 1 req/s

    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Borrador escrito en {OUTPUT_MD.relative_to(REPO_ROOT)}. Requiere revisión manual.")


if __name__ == "__main__":
    if not SOURCE_CSV.exists():
        print("No se encuentra el CSV de origen", file=sys.stderr)
        sys.exit(1)
    main()
