# Overlay local de portales (piloto Bizkaia)

Nominatim autoalojado sigue siendo el geocodificador **primario**. El overlay
solo aporta un punto de portal cuando OSM no tiene `addr:housenumber` para esa
calle+número y existe una fuente independiente. No se relaja el umbral de
RF-05 ni se usa un geocodificador de pago.

## Por qué existe

El extracto OSM de Euskadi cubre mal los portales de varias calles de Bilbao.
Reimportar Nominatim no arregla lo que no está en OSM. Un gazetteer local
(CSV/GeoJSON) es el recorte correcto para el piloto: se carga en memoria,
se consulta por clave normalizada `calle + número + municipio [/CP]` y se
inyecta como candidato `house` **después** de Nominatim (y de la caché).

Código: `backend/app/modules/geocoding/overlay.py`
Datos seed: `backend/app/modules/geocoding/data/housenumber_overlay.csv`

## Fuente del seed actual

Callejero oficial de la C.A. de Euskadi (Eustat, **CC-BY 4.0**), fichero de
portales de Bizkaia, cruzado con Cartociudad (IGN) y, cuando coincidía, con
nodos OSM ya existentes:

- <https://www.eustat.eus/comun/ExtractorBlob.ashx?id=48_Atariak_Portales.csv>
- Cartociudad `find`: <https://www.cartociudad.es/geocoder/api/geocoder/find>

| Calle (consulta GT) | Portal | CP overlay | Lat | Lon | ¿Por qué está? |
|---|---|---|---|---|---|
| Rekalde / Recalde | 33 | 48009 | 43.263570 | -2.934599 | Portal oficial Alameda Recalde 33. OSM lo tiene como `Recalde zumarkalea` 33; Nominatim no lo encuentra con «Calle Rekalde». |
| Mazarredo | 15 | 48001 | 43.264488 | -2.929373 | Portal oficial y nodo OSM. El GT trae CP 48009; el callejero/OSM usan 48001. |
| Zumalakarregi | 40 | 48006 | 43.257576 | -2.913169 | Portal oficial (Cartociudad + Eustat). El GT trae CP 48007; el callejero usa 48006. |
| Iparragirre / Iparraguirre | 60 | 48010 | 43.257681 | -2.938928 | Portal oficial y nodo OSM. Nominatim solo acierta con la grafía «Iparraguirre». |
| Bengoetxe (auzoa) | 5 | 48960 | 43.232828 | -2.860011 | Portal oficial del barrio (Eustat + Cartociudad `16.PV.MUN_480360160272`). OSM no tiene `addr:housenumber` 5. Añadido 2026-08-30 con el GT opción 1. |

No se siembran Zabalbide 92, Iturribide 54 ni Avenida Kirikiño 2: Nominatim local ya
devuelve `place=house` para esos portales oficiales.

### Números que **no** se siembran (siguen sin existir en Eustat)

El callejero Eustat de Bizkaia (96 217 portales, consultado 2026-08-30) **no
contiene** estos portales. Inventarlos violaría RF-05. El GT de 0.QA.2 se enmendó
el 2026-08-30 para **dejar de pedirlos**:

| ID | Dirección antigua (inválida) | Evidencia | GT desde 2026-08-30 |
|---|---|---|---|
| PAC-004 | Calle Zabalbide 90, 48006 Bilbao | Zabalbide salta de 82 a 92. Cartociudad `find` devolvía el 92 (vecino, no el 90). | Zabalbide **92** (OSM ya lo tiene; overlay innecesario). |
| PAC-005 | Calle Iturribide 55, 48006 Bilbao | Iturribide tiene 53, 54, 56. No hay 55. Cartociudad `find` devolvía el 54. | Iturribide **54** (OSM ya lo tiene). |
| PAC-010 | Calle Kirikiño 3, 48004 Bilbao | La única vía Kirikiño es la avenida en **48012**, con 1, 2, 4… (sin 3). No hay Kirikiño en 48004. | **Avenida** Kirikiño **2**, **48012**. |
| PAC-037 | Barrio Bengoetxe 4, 48960 Galdakao | Bengoetxe (barrio) empieza en el 5. No hay portal 4. | Bengoetxe **5** (overlay Eustat; ver tabla de seed). |

El overlay **nunca** indexa 90/55/3/4. Catastro DGC (ovc.catastro.meh.es) **no cubre
Bizkaia** (catastro foral). El WFS INSPIRE estatal de direcciones devuelve vacío en
el bbox de Bilbao.

`HousenumberOverlay.augment` solo omite el overlay si Nominatim ya trajo **este**
portal (mismo número **y** misma vía en `display_label`). Un homónimo en otra calle
(p.ej. Olabarrieta 5, CP 48970, al consultar Bengoetxe 5) **no** cuenta.

## Cómo refrescar el overlay desde el callejero

1. Descargar el CSV de portales de Bizkaia (CC-BY 4.0, ~23 MiB):

   ```bash
   curl -L -o /tmp/48_Atariak_Portales.csv \
     "https://www.eustat.eus/comun/ExtractorBlob.ashx?id=48_Atariak_Portales.csv"
   ```

2. Generar CSV o GeoJSON para los municipios piloto:

   ```bash
   PYTHONPATH=backend backend/.venv/bin/python scripts/qa/refresh_housenumber_overlay.py \
     --eustat-csv /tmp/48_Atariak_Portales.csv \
     --municipios Bilbao,Galdakao \
     --out backend/app/modules/geocoding/data/housenumber_overlay.csv
   ```

   GeoJSON (mismo esquema de propiedades, geometría `Point` lon/lat):

   ```bash
   ... --format geojson --out /tmp/housenumber_overlay.geojson
   ```

3. El módulo carga el CSV por defecto al arrancar (`get_default_overlay`).
   `HousenumberOverlay.from_geojson` sirve para el mismo fichero en GeoJSON.
   Tras cambiar el CSV hay que reciclar el proceso API (el índice va en
   `lru_cache`). La caché Redis de Nominatim **no** incluye el overlay: se
   aplica siempre después, así un refresh de portales no exige borrar Redis.

4. Atribución: mantener `source=eustat-callejero-bizkaia` y `source_ref` con
   la dirección oficial. Licencia del callejero: CC-BY 4.0 (Eustat).

## Cómo (no) volcar esto a OSM.org

Esto es un trabajo **aparte**, consciente de licencias. Este agente no sube
nada a OSM.

- El callejero Eustat es **CC-BY 4.0**. OSM es **ODbL**. Un import masivo de
  portales exige propuesta en la wiki de imports, atribución y acuerdo de la
  comunidad local (Talk-es / Euskadi). No se hace «de pasada» desde Sofia.
- Cartociudad/IGN tiene condiciones propias; no se asume compatible con ODbL
  sin revisar la ficha de licencia vigente.
- Lo seguro para OSM: **reconocimiento in situ** de portales (StreetComplete,
  OsmAnd, JOSM) en las calles del piloto (Zabalbide, Iturribide, Kirikiño,
  Recalde, Mazarredo, Zumalakarregi, Iparraguirre). El overlay de Sofia y el
  mapa OSM se mantienen como capas distintas hasta que OSM tenga el portal.

## Techo rural (caseríos)

Cuando la consulta **no trae número de portal**, el overlay no actúa. El
arreglo de Nominatim jsonv2 (`category`/`type` → `place_class`) permite
clasificar el nodo `place=village|hamlet|neighbourhood` como centro honesto
del caserío y dejar fuera bus-stops/carreteras con el mismo topónimo.

Sigue sin haber un portal único que inventar para un caserío **sin** número.
PAC-037 pasó de Bengoetxe 4 (inexistente) a Bengoetxe 5 (oficial Eustat) el
2026-08-30; el overlay aporta ese punto porque OSM no lo tiene. Un caserío
del GT sin número de portal oficial sigue yendo a `ambiguous`/`not_found`.

## Validar

```bash
PYTHONPATH=backend backend/.venv/bin/python scripts/qa/validate_matching_rate.py
```
