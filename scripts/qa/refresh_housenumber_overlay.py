"""Regenera el gazetteer de portales desde el callejero oficial de Eustat.

Fuente: Callejero de la C.A. de Euskadi (CC-BY 4.0), fichero de portales de Bizkaia:
https://www.eustat.eus/comun/ExtractorBlob.ashx?id=48_Atariak_Portales.csv

Uso (desde la raíz del repo):

  PYTHONPATH=backend backend/.venv/bin/python scripts/qa/refresh_housenumber_overlay.py \\
      --eustat-csv /ruta/48_Atariak_Portales.csv \\
      --municipios Bilbao,Galdakao \\
      --out backend/app/modules/geocoding/data/housenumber_overlay.csv

Por defecto NO descarga el CSV (23 MiB). Pásalo ya descargado. El seed del repo
es un recorte justificado de portales del piloto; este script sirve para ampliarlo.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "backend" / "app" / "modules" / "geocoding" / "data" / "housenumber_overlay.csv"
EUSTAT_URL = "https://www.eustat.eus/comun/ExtractorBlob.ashx?id=48_Atariak_Portales.csv"

FIELDNAMES = [
    "street",
    "house_number",
    "municipality",
    "postal_code",
    "latitude",
    "longitude",
    "source",
    "source_ref",
    "aliases",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eustat-csv", type=Path, required=True, help="CSV de portales Eustat (Bizkaia)")
    parser.add_argument(
        "--municipios",
        default="Bilbao",
        help="Municipios separados por coma (nombre Eustat, p.ej. Bilbao,Galdakao)",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--format",
        choices=("csv", "geojson"),
        default="csv",
        help="Formato de salida del overlay",
    )
    return parser.parse_args()


def _iter_points(path: Path, municipalities: set[str]):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for row in reader:
            muni = (row.get("Udalerria/Municipio") or "").strip()
            if muni not in municipalities:
                continue
            number = (row.get("Zenbakia/Número") or "").strip()
            if not number or number == "0":
                continue
            lat = (row.get("LAT_ETRS89") or "").strip()
            lon = (row.get("LON_ETRS89") or "").strip()
            if not lat or not lon:
                continue
            street = (row.get("Izena/Nombre") or "").strip()
            cp = (row.get("Posta-kodea/Código Postal") or "").strip()
            official = (row.get("Posta-helbidea/Dirección postal") or "").strip()
            yield {
                "street": street,
                "house_number": number,
                "municipality": muni,
                "postal_code": cp,
                "latitude": lat,
                "longitude": lon,
                "source": "eustat-callejero-bizkaia",
                "source_ref": official,
                "aliases": "",
            }


def _write_csv(path: Path, points: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(points)


def _write_geojson(path: Path, points: list[dict]) -> None:
    import json

    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(p["longitude"]), float(p["latitude"])],
            },
            "properties": {
                "street": p["street"],
                "house_number": p["house_number"],
                "municipality": p["municipality"],
                "postal_code": p["postal_code"],
                "source": p["source"],
                "source_ref": p["source_ref"],
                "aliases": [a for a in p["aliases"].split("|") if a],
            },
        }
        for p in points
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    args = _parse_args()
    if not args.eustat_csv.is_file():
        print(f"No existe {args.eustat_csv}. Descárgalo de:\n  {EUSTAT_URL}", file=sys.stderr)
        return 1
    municipalities = {name.strip() for name in args.municipios.split(",") if name.strip()}
    points = list(_iter_points(args.eustat_csv, municipalities))
    if args.format == "geojson":
        _write_geojson(args.out, points)
    else:
        _write_csv(args.out, points)
    print(f"Escritos {len(points)} portales de {sorted(municipalities)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
