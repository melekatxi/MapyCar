# Extracto OSM importado (0.DATA.5)

| Campo | Valor |
|---|---|
| Fuente | Geofabrik (`https://download.geofabrik.de/europe/spain/pais-vasco-latest.osm.pbf`) |
| Región | País Vasco (incluye Bizkaia) |
| Timestamp de los datos OSM | 2026-08-28T20:20:46Z (según cabecera del `.pbf` importado) |
| Perfil de enrutado OSRM | `car.lua` (perfil de coche por defecto de OSRM v5.27.1) |
| Algoritmo OSRM | MLD (`osrm-partition` + `osrm-customize`) |
| Imagen Nominatim | `mediagis/nominatim:4.5` |
| Imagen OSRM | `ghcr.io/project-osrm/osrm-backend:v5.27.1` |

## Procedimiento

- Nominatim descarga e importa el `.pbf` automáticamente al arrancar el contenedor
  (`docker compose up -d nominatim`), usando `PBF_URL` de `docker-compose.yml`.
- OSRM requiere preprocesar el mismo extracto antes de arrancar:
  `bash scripts/infra/prepare_osrm_data.sh` (extract → partition → customize),
  luego `docker compose up -d osrm`.

## Smoke test (criterio de aceptación)

Geocodificación de 5 municipios de referencia contra la instancia propia
(`http://localhost:8080/search`), ejecutada el 2026-08-29:

| Municipio | Resultado |
|---|---|
| Bilbao | 43.2630018, -2.9350039 |
| Barakaldo | 43.2949177, -2.9887476 |
| Getxo | 43.3431164, -3.0078627 |
| Portugalete | 43.3189646, -3.0198633 |
| Durango | 43.1707065, -2.6334897 |

Enrutado OSRM verificado con `/route` y `/table` (matriz 5x5) sobre coordenadas de Bizkaia
en `http://localhost:5001`, ambos con respuesta `"code":"Ok"`.

## Actualización del extracto

Para actualizar a un extracto más reciente: cambiar `NOMINATIM_PBF_URL` (o el valor por
defecto en `docker-compose.yml`), reimportar Nominatim (`docker compose up -d --force-recreate nominatim`,
que reimporta desde cero) y volver a ejecutar `prepare_osrm_data.sh` para regenerar los
ficheros `.osrm.*`. Documentar aquí el nuevo timestamp/fecha de importación.
