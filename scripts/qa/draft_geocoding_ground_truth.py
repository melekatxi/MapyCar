"""Genera un BORRADOR de verdad de referencia de geocodificación (0.QA.2).

Consulta preferentemente la instancia Nominatim autoalojada (0.DATA.5, ADR-07) y, si no
está disponible, cae a la instancia pública (uso de desarrollo, bajo volumen, respetando
1 req/s y un User-Agent identificable) para una muestra de 30 direcciones ficticias del
dataset de Bizkaia. La dirección se normaliza retirando piso/puerta antes de geocodificar
(igual que hará el worker de 1.BE.8), ya que ese detalle no existe como entidad en OSM.
El resultado sigue siendo un borrador: requiere revisión y aprobación manual por una
persona antes de usarse como ground truth (criterio de 0.QA.2).
"""
from __future__ import annotations

import csv
import re
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_CSV = REPO_ROOT / "docs" / "requisitos" / "direcciones-ejemplo-bizkaia.csv"
OUTPUT_MD = REPO_ROOT / "docs" / "requisitos" / "ground-truth-geocoding-draft.md"
USER_AGENT = "sofia-app-dev/0.1 (uso manual de bajo volumen, contacto: soporte@sofia.example)"
SELF_HOSTED_BASE_URL = "http://localhost:8080"
PUBLIC_BASE_URL = "https://nominatim.openstreetmap.org"
SAMPLE_SIZE = 30


def load_sample() -> list[dict[str, str]]:
    with SOURCE_CSV.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    urban = [r for r in rows if r["tipo_zona"] == "Urbana"][:15]
    rural = [r for r in rows if r["tipo_zona"] == "Rural"][:15]
    return urban + rural


def simplify_street(direccion: str) -> str:
    """Retira piso/puerta (todo tras la primera coma); OSM no modela esa unidad."""
    return re.split(r",", direccion, maxsplit=1)[0].strip()


def detect_base_url(client: httpx.Client) -> tuple[str, bool]:
    """Devuelve (base_url, es_autoalojada). Prefiere la instancia propia si responde."""
    try:
        response = client.get(f"{SELF_HOSTED_BASE_URL}/status.php", timeout=5.0)
        if response.status_code == 200:
            return SELF_HOSTED_BASE_URL, True
    except httpx.HTTPError:
        pass
    return PUBLIC_BASE_URL, False


def geocode(row: dict[str, str], client: httpx.Client, base_url: str) -> dict:
    # Búsqueda en texto libre, igual que NominatimGeocoder (app/adapters/geocoder/nominatim.py):
    # la búsqueda estructurada (street/city/postalcode) es más estricta y falla en caseríos/
    # barrios rurales sin capa de calle propia, aunque el nombre real exista en OSM.
    query = ", ".join(
        part for part in (simplify_street(row["direccion"]), row["codigo_postal"], row["municipio"]) if part
    )
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 1,
    }
    response = client.get(
        f"{base_url}/search", params=params, headers={"User-Agent": USER_AGENT}, timeout=15.0
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        return {"lat": None, "lon": None, "display_name": None}
    top = results[0]
    return {"lat": top["lat"], "lon": top["lon"], "display_name": top["display_name"]}


def main() -> None:
    sample = load_sample()[:SAMPLE_SIZE]
    with httpx.Client() as client:
        base_url, self_hosted = detect_base_url(client)
        source_label = "instancia autoalojada (localhost:8080)" if self_hosted else "instancia pública openstreetmap.org"
        lines = [
            "# Borrador de verdad de referencia de geocodificación (0.QA.2)",
            "",
            "> **Estado: BORRADOR generado automáticamente contra "
            f"{source_label}.**",
            "> Pendiente de revisión y aprobación manual por una persona antes de usarse",
            "> como ground truth para medir el criterio de aceptación RF-05 (≥95% `matched`).",
            "> La consulta usa calle+número normalizados (sin piso/puerta), igual que hará",
            "> el worker de geocodificación (1.BE.8); el piso/puerta original se conserva",
            "> en la columna Dirección para referencia.",
            "",
            "| ID | Dirección | CP | Municipio | Tipo | Lat (borrador) | Lon (borrador) | Resultado Nominatim |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for row in sample:
            result = geocode(row, client, base_url)
            lines.append(
                f"| {row['id_paciente']} | {row['direccion']} | {row['codigo_postal']} | "
                f"{row['municipio']} | {row['tipo_zona']} | {result['lat'] or '—'} | "
                f"{result['lon'] or '—'} | {result['display_name'] or 'NOT_FOUND'} |"
            )
            if not self_hosted:
                time.sleep(1.0)  # política de uso de Nominatim público: máximo 1 req/s

    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Borrador escrito en {OUTPUT_MD.relative_to(REPO_ROOT)}. Requiere revisión manual.")


if __name__ == "__main__":
    if not SOURCE_CSV.exists():
        print("No se encuentra el CSV de origen", file=sys.stderr)
        sys.exit(1)
    main()
