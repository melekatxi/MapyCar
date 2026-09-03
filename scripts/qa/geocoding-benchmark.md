# Benchmark de geocodificación (RNF-01 / 1.BE.14)

| Campo | Valor |
|---|---|
| Fecha | 2026-08-29 |
| Instancia | Nominatim autoalojado (`http://localhost:8080`), extracto País Vasco (ver [extracto-osm.md](../infra/extracto-osm.md)) |
| Script | [benchmark_geocoding.py](benchmark_geocoding.py) |
| Dataset | `docs/requisitos/direcciones-ejemplo-bizkaia.csv` (120 filas) |
| Hardware | Portátil de desarrollo (HP Victus, Intel i7-12700H, 32 GiB RAM), Nominatim/OSRM/DB en contenedores Docker en la misma máquina |

## Resultado

- **120 direcciones geocodificadas en 22.00 s** (5.46 direcciones/s).
- **Proyección lineal para 200 direcciones: ~36.7 s** (0.61 min).
- Criterio RNF-01 ("lote de 200 direcciones geocodificado en menos de 5 minutos contra
  instancia propia"): **cumplido con amplio margen** (~8x más rápido que el límite).

## Nota sobre calidad de match (no es el objeto de este benchmark)

Este script mide **rendimiento**, no precisión. Sobre el dataset completo (120 filas,
no solo la muestra de 30 de 0.QA.2) el resultado fue `{'matched': 13, 'ambiguous': 27,
'not_found': 80}`: la mayoría de las 56 filas rurales fuera de la muestra de ground truth
siguen usando el patrón ficticio `{Municipio} Auzoa {N}` (igual que las que se corrigieron
en 0.QA.2, pero esas 41 filas adicionales no se tocaron). El criterio de precisión de RF-05
(≥95% `matched`) se evalúa contra el ground truth aprobado de 30 direcciones (0.QA.2), no
contra el dataset completo; si se quiere medir precisión sobre las 120 filas habría que
regenerar también esas direcciones rurales restantes con nombres reales de OSM.

## Validación de precisión (1.BE.10) contra el ground truth de 0.QA.2 — HALLAZGO

Script: [validate_matching_rate.py](validate_matching_rate.py). Ejecuta el pipeline real
(normalización + scoring + clasificación) sobre las 28 direcciones "bien formateadas" del
ground truth aprobado (excluye las 2 filas rurales intencionadamente ficticias).

| Fecha | Pipeline | matched | Tasa | Notas |
|---|---|---|---|---|
| 2026-08-29 | Scorer real, Nominatim local, **sin** overlay | 15/28 | 53.6% | Baseline 1.BE.10. Por debajo de ≥95%. |
| 2026-08-30 | + overlay Eustat + `place_class` jsonv2 | 24/28 | 85.7% | 3 `ambiguous` + 1 `not_found`. Techo honesto: 4 portales del GT no existen en Eustat. |
| 2026-08-30 | + GT opción 1 (4 portales oficiales) + overlay Bengoetxe 5 | **28/28** | **100%** | RF-05 ≥95% cumplido. 0 `ambiguous`, 0 `not_found` en el denominador de 28. |

No se ha relajado el umbral ni se ha usado un geocodificador de pago. Procedimiento del
overlay: [geocoding-overlay.md](geocoding-overlay.md). Script:
`PYTHONPATH=backend backend/.venv/bin/python scripts/qa/validate_matching_rate.py`.

### Qué cambió el 2026-08-30

- **Nominatim jsonv2**: el adaptador leía `class`, que en jsonv2 se llama `category`, y
  ignoraba `type`. Los caseríos (`place=village|hamlet|neighbourhood`) puntuaban como
  carreteras homónimas → `ambiguous`. Corregido: el nodo de lugar es el centro honesto.
- **Overlay local** (`app/modules/geocoding/overlay.py`): gazetteer calle+número+municipio
  sembrado con portales del callejero Eustat (CC-BY 4.0) cruzados con Cartociudad/OSM.
  Nominatim sigue siendo primario; el overlay solo aporta el portal si OSM no lo trae.

Pasan a `matched` (antes fallaban): PAC-007 Recalde/Rekalde 33, PAC-008 Mazarredo 15,
PAC-011 Zumalakarregi 40, PAC-034 Galbarriatu, PAC-046 Sallabente, PAC-048 Irazola Auzoa,
PAC-052 Luparia, PAC-054 Gabika, PAC-060 Abaroa. PAC-013 Iparragirre 60 sigue `matched`
pero ahora con portal real (antes era el centroide de la calle).

### Cierre 2026-08-30 (opción 1): GT corregido a portales oficiales

Inventariados contra Nominatim local (`localhost:8080`, extracto País Vasco) y el
callejero Eustat de Bizkaia (96 217 portales, 2026-08-30). Catastro DGC no cubre Bizkaia.
**No se inventaron** 90/55/3/4; se sustituyeron por el portal oficial de la misma vía.
Las 4 filas **siguen en el denominador** de 28.

| ID | Antes (inválido) | Después | Outcome 2026-08-30 | Evidencia |
|---|---|---|---|---|
| PAC-004 | Calle Zabalbide 90, 48006 | Calle Zabalbide **92**, 48006 | `matched` | Eustat salta 82→92. Cartociudad `16.PV.MUN_480200149601`. Nominatim local `place=house` 92. Overlay **no** hace falta. |
| PAC-005 | Calle Iturribide 55, 48006 | Calle Iturribide **54**, 48006 | `matched` | Eustat 53, 54, 56 (no 55). Cartociudad `16.PV.MUN_480200143375`. Nominatim `place=house` 54. El 56 también geocodifica; se eligió 54. |
| PAC-010 | Calle Kirikiño 3, 48004 | **Avenida** Kirikiño **2**, **48012** | `matched` | Vía oficial = etorbidea 48012 (1, 2, 4…; no 3). Cartociudad `16.PV.MUN_480200144040`. Nominatim 0 candidatos con «Calle»; `place=house` 2 con «Avenida». |
| PAC-037 | Barrio Bengoetxe 4, 48960 Galdakao | Barrio Bengoetxe **5** | `matched` | Eustat el barrio empieza en 5. Cartociudad `16.PV.MUN_480360160272`. OSM no tiene `addr:housenumber` 5 → overlay Eustat. Nominatim devolvía el 5 de Olabarrieta (48970); `augment` ya no lo trata como el mismo portal. |

Run final (`validate_matching_rate.py`, Nominatim local arriba): **28/28 (100%)
`matched`**, 0 `ambiguous`, 0 `not_found`. RF-05 ≥95% (27/28) cumplido. 1.DATA.3 [x].

El borrador de 0.QA.2 parecía tener mejor tasa de acierto porque su script solo tomaba el
**primer resultado de Nominatim sin ningún scoring de confianza** — no es comparable con
la clasificación rigurosa de 1.BE.10, que es intencionadamente más conservadora (ADR de
diseño: "no se acepta automáticamente una coordenada de centroide/aproximada como
domicilio"). El 80% first-hit del 29 **no** se reescribe como si ya cubriera RF-05.

