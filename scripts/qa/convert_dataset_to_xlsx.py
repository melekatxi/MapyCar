"""Convierte el dataset ficticio de Bizkaia (CSV ';') a .xlsx y genera un informe de
comprobaciones automáticas (acentos, pisos, CP repetidos) como apoyo a la validación
manual exigida por 0.QA.1. La validación manual final la debe firmar una persona.
"""
from __future__ import annotations

import csv
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from openpyxl import Workbook

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_CSV = REPO_ROOT / "docs" / "requisitos" / "direcciones-ejemplo-bizkaia.csv"
OUTPUT_XLSX = REPO_ROOT / "docs" / "requisitos" / "direcciones-ejemplo-bizkaia.xlsx"
FLOOR_MARKERS = ("º", "Bajo", "Ático")


def _has_accents(text: str) -> bool:
    return any(unicodedata.combining(c) for c in unicodedata.normalize("NFD", text))


def convert() -> list[dict[str, str]]:
    with SOURCE_CSV.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "pacientes"
    sheet.append(fieldnames)
    for row in rows:
        sheet.append([row[field] for field in fieldnames])
    workbook.save(OUTPUT_XLSX)
    return rows


def validate(rows: list[dict[str, str]]) -> None:
    accented = sum(1 for r in rows if _has_accents(r["direccion"]) or _has_accents(r["municipio"]))
    with_floor = sum(1 for r in rows if any(m in r["direccion"] for m in FLOOR_MARKERS))
    postal_by_municipality: dict[str, set[str]] = {}
    for r in rows:
        postal_by_municipality.setdefault(r["codigo_postal"], set()).add(r["municipio"])
    repeated_postal_codes = {cp: munis for cp, munis in postal_by_municipality.items() if len(munis) > 1}
    zone_counts = Counter(r["tipo_zona"] for r in rows)

    print(f"Filas totales: {len(rows)}")
    print(f"Filas con acentos (dirección/municipio): {accented}")
    print(f"Filas con indicador de piso/portal: {with_floor}")
    print(f"Códigos postales compartidos por >1 municipio: {len(repeated_postal_codes)}")
    print(f"Distribución por tipo de zona: {dict(zone_counts)}")
    print(f"Fichero .xlsx generado en: {OUTPUT_XLSX.relative_to(REPO_ROOT)}")
    print("Pendiente: validación manual de esta muestra por una persona antes de usarla como fixture (DoD).")


if __name__ == "__main__":
    if not SOURCE_CSV.exists():
        print(f"No se encuentra el CSV de origen: {SOURCE_CSV}", file=sys.stderr)
        sys.exit(1)
    rows = convert()
    validate(rows)
