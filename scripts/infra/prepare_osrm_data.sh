#!/usr/bin/env bash
# Descarga el extracto OSM y ejecuta extract/partition/customize para OSRM.
# Ref: 0.DATA.5. Debe ejecutarse antes de levantar el servicio `osrm` de docker-compose.yml.
set -euo pipefail

PBF_URL="${1:-https://download.geofabrik.de/europe/spain/pais-vasco-latest.osm.pbf}"
FILENAME="$(basename "$PBF_URL")"
BASENAME="${FILENAME%.osm.pbf}"
VOLUME_NAME="sofia-dev_osrm_data"
OSRM_IMAGE="ghcr.io/project-osrm/osrm-backend:v5.27.1"

echo "==> Descargando ${PBF_URL} en el volumen ${VOLUME_NAME}"
docker run --rm --user root -v "${VOLUME_NAME}:/data" curlimages/curl:8.10.1 \
  -sSL -o "/data/${FILENAME}" "${PBF_URL}"

echo "==> osrm-extract"
docker run --rm -v "${VOLUME_NAME}:/data" "${OSRM_IMAGE}" \
  osrm-extract -p /opt/car.lua "/data/${FILENAME}"

echo "==> osrm-partition"
docker run --rm -v "${VOLUME_NAME}:/data" "${OSRM_IMAGE}" \
  osrm-partition "/data/${BASENAME}.osrm"

echo "==> osrm-customize"
docker run --rm -v "${VOLUME_NAME}:/data" "${OSRM_IMAGE}" \
  osrm-customize "/data/${BASENAME}.osrm"

echo "==> Listo. Actualiza el entrypoint de docker-compose.yml a /data/${BASENAME}.osrm si el nombre difiere."
