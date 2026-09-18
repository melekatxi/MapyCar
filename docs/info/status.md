# Estado del proyecto — App de Rutas de Visitas a Pacientes

> **Documento vivo.** Se actualiza en cada sesión de trabajo relevante: progreso por fase,
> deuda técnica nueva, decisiones pendientes y hallazgos que requieren decisión humana.
> No sustituye a [`docs/tareas/tareas-app-rutas-pacientes.md`](../tareas/tareas-app-rutas-pacientes.md)
> (fuente de verdad del desglose tarea a tarea) — este documento es el resumen ejecutivo
> y el registro de deuda/decisiones que no encajan como una tarea más del checklist.

| Campo | Valor |
|---|---|
| Última actualización | 2026-09-18 |
| Fase actual | Fase 4 **iniciada (11/20)**. Fase 3 20/20. Fase 2 19/19. Fase 1 código 27/28; único pendiente 1.FE.8 (humanos) |
| Siguiente | **4.BE.10** GET/PATCH notificaciones. **No** production-ready: ClamAV, DoD PR, usabilidad. No arrancar Fase 5 como camino principal. |

## 1. Resumen ejecutivo

- **Fase 0 (Preparación): 16/16 tareas completadas y verificadas.** Infraestructura Docker
  (Postgres+PostGIS, Redis, Nominatim, OSRM, Vault) funcionando de verdad en local, con
  extracto OSM de Euskadi importado. Backend FastAPI modular, adaptadores (Geocoder/Router/
  Optimizer/TileProvider/ObjectStore), identidad con RLS, CI con lint+tests+escaneo.
- **Fase 1 (MVP importación/geocodificación/mapa): 27/28.** El código de importación,
  geocodificación y mapa **existe** (pipeline CSV/XLSX/XLS, scoring, caché, Leaflet,
  ObjectStore S3 cifrado, leyendas RF-07 y detalle RF-08). 1.QA.1 y 1.QA.2 se cierran
  el 2026-08-30 (E2E HTTP en CI y formatos de importación del backend, incluido `.xls`).
  **1.DATA.3 [x] 2026-08-30**: RF-05 ≥95% cumplido — **28/28 (100%) `matched`** en las 28
  direcciones bien formateadas (baseline 15/28 → overlay 24/28 → GT opción 1 + overlay
  Bengoetxe 5 = 28/28). **Cierre de código 2026-08-30**: 1.DATA.4, 1.FE.5 y 1.FE.6 [x]
  (MVP). **Único pendiente: 1.FE.8** (sesiones con humanos; el protocolo no es el
  informe: [`docs/qa/usabilidad-fase1-protocolo.md`](../qa/usabilidad-fase1-protocolo.md)).
  **No** dar Fase 1 por production-ready: falta usabilidad humana y ClamAV
  (5.SEC.7). Ledger Idempotency-Key = **3.BE.14 `[x]`**.
- **Fase 2 (Zonificación y planificación): 19/19, cerrada a nivel de WBS
  2026-08-30.** Modelo de zonas (`zones`/`zone_assignments`, Alembic
  `7f30767de9b7`) y planes (`monthly_plans`/`daily_routes`, Alembic
  `bdf038e859a7`); features (EPSG:25830, densidad, urbano/rural, haversine
  al depósito); clustering capacitado (K-means urbano + DBSCAN rural,
  `max_visits`); cohesión OSRM **cableada** en `run_zone_proposal` con
  2.BE.7; propuestas HTTP + CRUD/override; calendario laborable y
  asignación diaria (200 ficticios Sep 2026); HTTP de planes (crear/
  generate 202 / GET / validate / PATCH visita dry-run+confirm). **Cierre
  2026-08-30:** publicar `POST /plans/{id}/publish` **200** (una
  transacción: `daily_routes` + `outbox_events` `plan.published`; Alembic
  `e4c8a2b91d07`; no 202); `PUT .../routes/{id}/assignee` (otra org →
  404) + `GET /plans/{id}/routes`; calendario UI `/planificacion`
  (`PlanCalendarPage`: drag + formulario, dry-run luego confirm,
  `GET /teams` / `GET /plans`; Vitest 30 passed; **sin** UI de publicar;
  **sin** Playwright); `ZoneKindBadge` urban/rural/mixed (SVG + label +
  clase) en editor y chips del calendario (18 tests planning+zoning);
  E2E HTTP [`test_fase2_e2e.py`](../../backend/tests/test_fase2_e2e.py)
  200 pacientes, proposal→override→plan generate→move→publish (**1
  passed** ~8 s; pytest, no Playwright). **Caveats visibles:** publish
  200 vs diseño 202; outbox en 2.BE.13, consumidor **4.BE.9 `[x]`**;
  assignee por defecto = planner salvo `body.assignees`; `GET /patients`
  **no** filtra field-only ni setea `visit_status` planned/completed
  (criterio 403/404 de 2.BE.14 sí). **1.FE.8** sigue humana. **No**
  production-ready (ClamAV, DoD PR, usabilidad). Ledger Idempotency-Key
  = **3.BE.14 `[x]`**. Deltas vs diseño: [§3.11](#311-deltas-de-esquema-fase-2-vs-diseño-61),
  [§3.12](#312-tabla-zone_proposals-no-está-en-diseño-61),
  [§3.13](#313-cohesión-osrm-no-está-en-el-worker-de-propuestas)
  (resuelto) y [§3.14](#314-publicar-plan-200-vs-202-outbox-adelantado).
- **Fase 3 (Optimización de rutas): 20/20, cerrada 2026-09-11.** Esquema
  `route_revisions`/`route_stops`/`route_metrics` (Alembic `c91d0e47f3b2`;
  UNIQUE `(route_id, revision)` y `(revision_id, sequence)`; FK
  `daily_routes.current_revision`; RLS) y ledger `jobs` (Alembic
  `d02e1f58a4c3` **head**; `begin_idempotent_job` → 409
  `IDEMPOTENCY_KEY_REUSE`). Matriz OSRM `/table` con caché Redis
  (`matrix.py`: 25 paradas, 2 `compute_matrix` → 1 `table()`; clave
  sha256 `profile|dataset|coords` redondeadas). `OrToolsTspOptimizer`
  (ortools 9.15; 25 paradas ~0.04 s). VRPTW: ventanas incompatibles →
  `ROUTING_INFEASIBLE` + diagnósticos, `order` vacío. Objetivo `time`
  vs `cost`. Métricas `original`+`optimized` con el mismo `matrix_hash`.
  HTTP: `POST /routes/{id}/optimize` (`Idempotency-Key`, cola
  `optimization`, `worker-optimization`); `GET /routes/{id}/comparison`
  (ahorro; 409 `METRICS_STALE`); `PATCH /routes/{id}/stops/order`
  (`If-Match` sobre `daily_routes.version`, métricas stale);
  `GET /routes/{id}` con diagnósticos y acciones sugeridas (códigos
  `INCOMPATIBLE_WINDOWS`, `ISOLATED_STOP`). **3.BE.11 `[x]` 2026-09-11:**
  `POST /routes/{id}/publish` **200** (snapshot inmutable: dirección
  cifrada, orden, métricas, geometría OSRM, versiones OSRM/OSM);
  reordenar la publicada → 409; optimize posterior crea revisión
  `draft`. Benchmark TSP p95 **0.0266 s** en i7-12700H
  ([`tsp-benchmark.md`](../../scripts/qa/tsp-benchmark.md)).
  **3.BE.9 `[x]` 2026-09-11:** `PUT /routes/{id}/stops` (añadir/quitar/
  refrescar direcciones; published abre `draft`); optimize incluye
  `stops_fingerprint` (misma clave tras el cambio → 409; clave nueva →
  202). **3.FE.1 `[x]` 2026-09-11:** UI `/optimizacion` lanza
  `POST /routes/{id}/optimize` y hace polling de `GET /jobs/{id}` hasta
  completar (Vitest, no Playwright). **3.FE.2 `[x]` 2026-09-11:**
  `RouteDiagnostics` en inviabilidad (explicación + acciones; no relaja
  solas). **3.FE.3 `[x]` 2026-09-11:** comparativa original/optimizada
  (tabla de ahorro + mapa numerado). **3.BE.13 `[x]` 2026-09-11:**
  `POST /routes/{id}/exports` 202 (pdf/png/navigation_link); enlace solo
  coords. **3.FE.4 `[x]` 2026-09-11:** UI exporta PDF/PNG y copia enlace
  (diálogo de riesgo Google Maps). **3.QA.2 `[x]` 2026-09-11:**
  [`test_routing_fase3_e2e.py`](../../backend/tests/test_routing_fase3_e2e.py)
  recalc → publish → export. **Pendientes (0).** **4.BE.1 `[x]`:**
  `GET /history/routes` sobre snapshots. **4.BE.2 `[x]` 2026-09-18:**
  `PATCH /routes/{id}/stops/{stopId}` ejecución (`If-Match` =
  `route_stops.version`; 409 con estado más reciente). **4.BE.3 `[x]`
  2026-09-18:** `route_metrics.variant=actual` al reportar; `GET
  /comparison` devuelve `actual`/`deviation`/`execution_counts` (sin GPS).
  **4.FE.1 `[x]` 2026-09-18:** UI `/historico` (filtros + snapshot + plan vs.
  ejecución). **4.FE.5 `[x]` 2026-09-18:** UI `/campo` (reporte + reconexión,
  sin teselas offline). **4.BE.5 `[x]` 2026-09-18:** `share_grants` CHECK
  sujeto XOR token + RLS. **4.BE.6 `[x]` 2026-09-18:** `POST/GET
  /routes/{id}/shares` interno; view no edita. **4.BE.7 `[x]` 2026-09-18:**
  token externo + `POST /public-shares/exchange` (410 vencido/revocado; vista
  minimizada). **4.BE.8 `[x]` 2026-09-18:** `DELETE /shares/{id}` invalida
  acceso al instante (403 interno / 410 exchange). **4.FE.2 `[x]`
  2026-09-18:** UI `/compartir` (interno/externo, preview, revocar).
  **4.BE.9 `[x]` 2026-09-18:** consumidor outbox idempotente (`event_id`);
  `notifications` + eventos share/reasignar. **Siguiente código:**
  **4.BE.10**. **1.FE.8** sigue humana.
- **Fase 4 iniciada (11/20).** Fase 5 y transversales: no como camino principal.
  T.CI.1/T.CI.2 son distintas de 0.CI.1/0.CI.2 (Fase 0, hechas).
- **RF-05 cerrado** — ver [sección 3.1](#31-tasa-de-matching-de-geocodificación-por-debajo-del-objetivo)
  (resuelto 2026-08-30) y [sección 3.10](#310-ground-truth-0qa2-contiene-portales-que-no-existen-en-el-callejero-oficial).

## 2. Estado por fase

| Fase | Tareas totales | Completadas | Pendientes | Notas |
|---|---|---|---|---|
| 0 — Preparación | 16 | 16 | 0 | Cerrada y aprobada (incluye aprobación manual de 0.QA.1/0.QA.2). 0.CI.1/0.CI.2 viven aquí, no en Transversal. |
| 1 — MVP importación/geocodificación/mapa | 28 | 27 | 1 | Pendiente: 1.FE.8 (humanos). Cerradas 2026-08-30: 1.DATA.3, 1.QA.1, 1.QA.2, 1.DATA.4, 1.FE.5, 1.FE.6. |
| 2 — Zonificación y planificación | 19 | 19 | 0 | **Hecha 2026-08-30 a nivel de WBS.** 2.BE.1–2.BE.14, 2.FE.1–2.FE.3, 2.QA.1, 2.QA.2. Pendientes: ninguna. Caveats: publish 200 vs 202; consumidor outbox **4.BE.9 `[x]`**; mapa field/`visit_status` real no; sin Playwright. |
| 3 — Optimización de rutas | 20 | 20 | 0 | **Cerrada 2026-09-11 (20/20).** Hechas las 20. |
| 4 — Histórico y colaboración | 20 | 11 | 9 | **Iniciada 2026-09-11 (11/20).** Hechas: 4.BE.1–3, 4.BE.5–9, 4.FE.1–2, 4.FE.5. Pendientes: 4.BE.4, 4.BE.10–13, 4.FE.3–4, 4.QA.1–2. **Siguiente código:** 4.BE.10. |
| 5 — Pruebas, seguridad y despliegue | 19 | 0 | 19 | No iniciada. Añadida 5.SEC.7 (ClamAV) el 2026-08-30. |
| Transversal (observabilidad, CI/CD, docs, RGPD) | 12 | 0 | 12 | **0/12, no 2/12.** 0.CI.1/0.CI.2 son Fase 0; T.CI.1/T.CI.2 (CD a staging y gate de cobertura) siguen abiertas. |
| **Total** | **134** | **93** | **41** | 16+27+19+20+11=93 hechas. +1 (4.BE.9) el 2026-09-18. 42−1=**41**. |

Detalle tarea a tarea con criterios de aceptación y evidencia: ver
[`docs/tareas/tareas-app-rutas-pacientes.md`](../tareas/tareas-app-rutas-pacientes.md).
Índice operativo de las 41 pendientes (qué está desbloqueado ya): [sección 6](#6-tareas-pendientes-índice-operativo).

## 3. Deuda técnica y decisiones pendientes (registro vivo)

> Añadir una entrada nueva por cada deuda/decisión que surja. No borrar entradas resueltas:
> marcarlas como **Resuelto** con fecha y enlace al cambio que las cerró.

### 3.1 Tasa de matching de geocodificación por debajo del objetivo

- **Estado**: 🟢 **Resuelto 2026-08-30** — 1.DATA.3 [x]. Evidencia:
  [`scripts/qa/geocoding-benchmark.md`](../../scripts/qa/geocoding-benchmark.md)
  (`validate_matching_rate.py` contra Nominatim local): **28/28 (100%) `matched`**.
  Umbral RF-05 ≥95% (27/28) cumplido. No se relajó el SLO ni se usó geocodificador de pago.
- **Detectado**: 2026-08-29, al validar 1.BE.10 contra el ground truth aprobado (0.QA.2).
- **Qué pasaba (baseline 2026-08-29)**: el scorer de geocodificación solo alcanzaba
  **15/28 (53.6%) `matched`** contra las 28 direcciones bien formateadas del ground
  truth, muy por debajo del ≥95% que exige RF-05. 1.BE.10 queda [x] como scorer
  implementado; el gate ≥95% era de **1.DATA.3**.
- **Progreso intermedio 2026-08-30** (Nominatim en vivo + scorer real + overlay, **antes**
  de corregir el GT): **24/28 (85.7%) `matched`**, 3 `ambiguous`, 1 `not_found`. Techo
  honesto 24/28 mientras el GT tenía 4 portales inexistentes. Overlay:
  `backend/app/modules/geocoding/overlay.py` + `data/housenumber_overlay.csv`. Nominatim
  sigue siendo el proveedor primario.
- **Bugfix colateral**: el adaptador Nominatim jsonv2 ignoraba `category`/`type`
  (`place_class`), así que aldeas empataban con carreteras homónimas. Eso recuperó
  varios matches rurales.
- **Cierre (opción 1 ejecutada 2026-08-30)**: se corrigieron los 4 fixtures a portales
  oficiales (ver [3.10](#310-ground-truth-0qa2-contiene-portales-que-no-existen-en-el-callejero-oficial)).
  Overlay de Bengoetxe 5 (Eustat; OSM no tiene el housenumber). `augment` ya no trata un
  portal homónimo en otra vía (Olabarrieta 5) como el mismo portal. Re-run:
  **28/28 (100%)**. Las 4 filas **siguen en el denominador**.
- **Causa raíz** (no era un bug del scorer): cobertura incompleta de números de portal
  en OSM **y** 4 números del GT que el callejero oficial no tiene. El 80% first-hit del
  0.QA.2 original no es comparable: aceptaba el primer resultado de Nominatim sin scoring.
- **Detalle completo**: [`scripts/qa/geocoding-benchmark.md`](../../scripts/qa/geocoding-benchmark.md).
- **Decisión (2026-08-30)**: A+B+C en conjunto; para el matching, **A = opción 1**.
  No se insertaron las coordenadas del ground truth en el matcher (circular). No se volcó
  Eustat a OSM.org.
- **Opciones descartadas** (se dejan escritas, no se reescriben):
  1. ~~Mejorar la cobertura del extracto OSM~~ → **elegida y cerrada** en 1.DATA.3.
  2. Relajar el criterio de aceptación para direcciones `ambiguous`.
  3. Proveedor de geocodificación de pago (RNF-10).
- **Ya no bloquea** RF-05. Fase 1 sigue sin estar production-ready.
- **Actualización 2026-08-30 (cierre docs Fase 1):** 1.DATA.4, 1.FE.5 y 1.FE.6 cerrados
  como MVP. Sigue abierto **1.FE.8** (humanos). ClamAV = 5.SEC.7. Idempotency ledger =
  **3.BE.14 `[x]`**. Datos reales planned/completed y filtro field-only en `GET /patients`
  **no** se cerraron con 2.BE.14 (assignee HTTP sí); residual en [§3.6](#36-restricciones-por-rol-y-estados-de-ruta-pendientes-de-fase-234).

### 3.2 Antivirus real no implementado en la importación

- **Estado**: 🟡 Abierto — deuda técnica conocida, no bloqueante para el MVP.
- **Qué falta**: 1.BE.1 solo valida firma real del fichero (magic bytes), tamaño máximo
  y número de filas. No hay escaneo antivirus real (p. ej. ClamAV).
- **Por qué no se hizo**: no es uno de los adaptadores documentados en ADR-06 y requeriría
  desplegar un nuevo servicio en `docker-compose.yml`. Se dejó fuera de alcance de 1.BE.1
  para no inflar esa tarea con infraestructura nueva no planificada.
- **Acción**: hueco cerrado como tarea **5.SEC.7** (2026-08-30). Sigue sin implementar.

### 3.3 Idempotency-Key sin ledger de petición/respuesta

- **Estado**: 🟢 **Resuelto 2026-08-30** — 3.BE.14 `[x]`.
- **Qué faltaba**: la cabecera `Idempotency-Key` se exigía (400 si falta) en
  `POST /imports` y `POST /imports/{id}/commit`, pero no había una tabla que
  comparase el hash de la petición con reintentos usando la misma clave
  (diseño §8.1: "reutilizar clave con payload distinto devuelve 409").
- **Mitigación que quedó**: para `POST /imports`, el índice único parcial
  `(organization_id, period, file_sha256)` sigue siendo la deduplicación de
  fichero/periodo (1.BE.7). Ese camino **no** pasa por el ledger `jobs`.
- **Cierre**: Alembic `d02e1f58a4c3` (**head**) crea `jobs` con UNIQUE
  `(organization_id, type, idempotency_key)` y `request_hash` (sha256 del
  payload canónico). `begin_idempotent_job`: misma clave + payload distinto
  → **409 `IDEMPOTENCY_KEY_REUSE`**. Consumidor: `POST /routes/{id}/optimize`
  (3.BE.7). Tests: [`test_jobs_ledger.py`](../../backend/tests/test_jobs_ledger.py).
- **Residual (no reabre la tarea)**: imports siguen sin el ledger; el hueco
  de diseño 8.1 está cubierto en el camino de optimización.

### 3.4 ObjectStore en memoria también en el "camino de producción"

- **Estado**: 🟢 **Resuelto 2026-08-30** — 1.DATA.4 [x]. Adaptador S3 cifrado AES-GCM
  (`S3ObjectStore` + `ObjectCipher`) y MinIO en `docker-compose.yml`. `get_object_store()`
  usa S3 cuando hay `SOFIA_S3_ENDPOINT_URL`; si falta, sigue InMemory (tests e2e van por
  override). Tests: `test_object_store_s3.py` (roundtrip con nueva instancia; at-rest no
  es plaintext).
- **Qué pasaba**: `get_object_store()` devolvía `InMemoryObjectStore`; los ficheros de
  `POST /imports` no sobrevivían un reinicio del proceso API.
- **Workers (2026-08-30)**: añadidos `worker-imports` y `worker-geocoding` al compose,
  misma imagen y env S3 que `api`. Sin eso, `python -m app.jobs.worker` caía en InMemory
  y no veía los uploads. El CLI exige una cola por proceso (`imports` / `geocoding`).
- **Acción original**: hueco del WBS cerrado como tarea **1.DATA.4** (2026-08-30).

### 3.5 Formato `.xls` (Excel binario legado) no soportado

- **Estado**: 🟢 Resuelto 2026-08-30 — 1.QA.2 [x].
- **Qué pasaba**: `parsing.py` solo soportaba CSV (`;`/`,`) y `.xlsx`. RNF-09 exige también
  `.xls`.
- **Resolución**: `xlrd` 2.0.2; `detect_format`/`parse_rows` para `.xls` (magic OLE2
  `D0 CF 11 E0`); tests `test_imports_parsing` + e2e upload 202. 22 parsing/validation
  en verde, 3 e2e xls en verde, ruff limpio. RNF-09 cubre formatos de importación del
  backend.
- **Residual de UI resuelto 2026-08-30**: el `ImportWizard` acepta
  `accept=".csv,.xlsx,.xls"` ([`ImportWizardPage.tsx`](../../frontend/src/imports/ImportWizardPage.tsx)).
  RNF-09 cubre backend **y** el selector del asistente.

### 3.6 Restricciones por rol y estados de ruta pendientes de Fase 2/3/4

- **Estado**: 🟡 Residual abierto — 1.FE.5 / 1.FE.6 cerradas 2026-08-30 como MVP de
  RF-07 / RF-08. 2.BE.14 `[x]` cubre el criterio 403/404 de assignee; **no** el
  enganche del mapa.
- **Qué hay hoy**: dos leyendas en el mapa (visita pendiente/planificada/completada +
  geocodificación). Marcadores por `visit_status` (relleno); hoy todos `pending`.
  Detalle al seleccionar: referencia, dirección minimizada (municipio/CP), día/zona =
  **Sin asignar**. El criterio viejo “field solo ve rutas asignadas” era sobre-spec
  frente a RF-08; no se finge RBAC de campo.
- **Qué cerró 2.BE.14 (2026-08-30)**: `PUT /plans/{id}/routes/{id}/assignee` +
  `GET /plans/{id}/routes`. Usuario de otra organización → **404**. Criterio de
  aceptación de la tarea (403/404 fuera de org) **cumplido**.
- **Qué sigue sin hacer (caveat, no hay fila WBS nueva)**: `GET /patients` / mapa
  **no** limitan el rol `field` a rutas asignadas ni alimentan `visit_status`
  planned/completed reales. `ShareGrant` (Fase 4) cubre compartidos. Hoy cualquier
  miembro de la organización ve todos los pacientes vía `GET /patients`.
- **Por qué no hay planned/completed reales**: `daily_routes` existe (2.BE.8) y
  nace al publicar (2.BE.13) con `assignee_id`, pero el listado de pacientes del
  mapa no lee esas filas.

### 3.7 `GET /patients` no está en el diseño de API documentado

- **Estado**: 🟢 Nota de consistencia, sin urgencia.
- **Qué pasa**: se añadió `GET /patients` (backend) para poder pintar el mapa operativo
  (1.FE.4) y alimentar la bandeja de geocodificación (1.FE.3), pero la sección 8.3 del
  documento de diseño no lo contempla explícitamente.
- **Acción recomendada**: incorporarlo a `docs/diseno/diseno-app-rutas-pacientes.md`
  sección 8.3 en la próxima revisión del diseño, para que el documento siga siendo la
  fuente de verdad del contrato de API.

### 3.8 `docker-compose.yml` es solo de desarrollo

- **Estado**: 🟢 Esperado — corresponde a Fase 5 (despliegue).
- **Qué pasa**: el `docker-compose.yml` de la raíz (con `api`, `frontend`, `db`, `redis`,
  `nominatim`, `osrm`, `vault`, `minio`, `worker-imports`, `worker-geocoding`,
  `worker-zoning`, `worker-planning`, `worker-optimization`) es de un
  solo host y sin TLS/reverse proxy/backups. Eso es exactamente lo que exige la sección 4
  del diseño para staging/producción (5.DEPLOY.*, 5.DATA.*), aún no abordado.

### 3.9 DoD general no cumplido en el árbol de trabajo actual

- **Estado**: 🟡 Abierto — proceso, no un RF.
- **Qué pasa**: el DoD de [`tareas-app-rutas-pacientes.md`](../tareas/tareas-app-rutas-pacientes.md)
  sección 3 exige PR con segundo revisor. El working tree de `main` está sucio (cambios
  locales sin PR). Las tareas [x] de Fase 0/1/2/3 acreditan código y tests, no el DoD de
  proceso.
- **Acción**: no tratar [x] como "listo para producción" mientras no haya PR revisado.

### 3.10 Ground truth 0.QA.2 contiene portales que no existen en el callejero oficial

- **Estado**: 🟢 **Resuelto 2026-08-30** — opción 1 ejecutada: GT enmendado a portales
  oficiales (Eustat CC-BY 4.0 + Cartociudad + Nominatim local). Las 4 filas **siguen en
  el denominador**. Aprobación original 2026-08-29 no se reescribe; la enmienda está
  fechada en [`ground-truth-geocoding-draft.md`](../requisitos/ground-truth-geocoding-draft.md).
- **Detectado**: 2026-08-30, al contrastar los 4 PAC sin match (tras overlay OSM) con
  Eustat + Cartociudad. Ver [3.1](#31-tasa-de-matching-de-geocodificación-por-debajo-del-objetivo).
- **Qué pasaba**: el ground truth de 0.QA.2 incluía números de portal que no aparecen en
  el índice oficial de calles.
- **Sustituciones (todas verificadas antes de escribir)**:

  | PAC | Antes (inválido) | Después (oficial) | Fuente |
  |---|---|---|---|
  | PAC-004 | Zabalbide **90**, 48006 | Zabalbide **92**, 48006 | Eustat salta 82→92; Cartociudad `16.PV.MUN_480200149601`; Nominatim `place=house` 92 |
  | PAC-005 | Iturribide **55**, 48006 | Iturribide **54**, 48006 | Eustat 53, 54, 56 (no 55); Cartociudad `16.PV.MUN_480200143375`; Nominatim `place=house` 54 |
  | PAC-010 | Kirikiño **3**, **48004** | Avenida Kirikiño **2**, **48012** | Vía oficial = etorbidea 48012 (1, 2, 4…; no 3). Cartociudad `16.PV.MUN_480200144040`. Nominatim 0 candidatos con «Calle» |
  | PAC-037 | Bengoetxe **4** | Bengoetxe **5** | Barrio oficial empieza en 5; Eustat + Cartociudad `16.PV.MUN_480360160272`; overlay (OSM sin housenumber) |

### 3.11 Deltas de esquema Fase 2 vs diseño §6.1

- **Estado**: 🟡 Nota de consistencia — registro vivo, **no** es un hueco del WBS.
- **Detectado**: 2026-08-30, al cerrar 2.BE.1 y 2.BE.8.
- **Qué hay en código** (el diseño no se reescribe aquí; se anota para la próxima revisión
  de [`diseno-app-rutas-pacientes.md`](../diseno/diseno-app-rutas-pacientes.md) §6.1):
  1. `zone_assignments.organization_id` NOT NULL + FK compuestas a `zones`/`patients`.
     El §6.1 omite `organization_id` en la lista de columnas de esa tabla (el párrafo
     introductorio sí dice que toda tabla multi-tenant lo incluye).
  2. UNIQUE de apoyo `patients (id, organization_id)` (`uq_patients_id_org`) y
     `teams (id, organization_id)` (`uq_teams_id_org`) para esas FK compuestas.
     No estaban en §6.1.
  3. `monthly_plans.status` usa `validating` (diseño §5.1: `draft → validating →
     published → archived`). **No** hay estado `validated` en planes — eso es
     `ImportBatch`.
  4. `monthly_plans.result_json`, `conflicts_json`, `job_id` (Alembic
     `024e6184b61b`, 2.BE.11). El solver persiste calendario/asignaciones/
     conflictos en el plan; no reutiliza `constraints_json`.
- **Acción**: incorporar a diseño §6.1 en la próxima revisión. No crear tarea WBS.
- **Ampliación 2026-08-30**: tabla `zone_proposals` (2.BE.5) — ver [3.12](#312-tabla-zone_proposals-no-está-en-diseño-61).
  Cohesión OSRM cableada en el worker (2.BE.7) — ver [3.13](#313-cohesión-osrm-no-está-en-el-worker-de-propuestas) (resuelto).
  `outbox_events` (2.BE.13, Alembic `e4c8a2b91d07`) — ver [3.14](#314-publicar-plan-200-vs-202-outbox-adelantado).

### 3.12 Tabla `zone_proposals` no está en diseño §6.1

- **Estado**: 🟡 Nota de consistencia — registro vivo, **no** es un hueco del WBS.
- **Detectado**: 2026-08-30, al cerrar 2.BE.5.
- **Qué hay en código**: tabla `zone_proposals` (Alembic `c8e41f7a02b3`, revises
  `bdf038e859a7`) para el job async de `POST /api/v1/zone-proposals` (202) y
  `GET /zone-proposals/{id}` (409 si no está lista). El recurso sí está en
  diseño §8.4; la tabla **no** aparece en §6.1. Las assignments del GET son
  ids de cluster de la propuesta, **no** filas de `zone_assignments`.
  Persistencia de zonas reales = **2.BE.6** `[x]` 2026-08-30 (`POST /zones`,
  PATCH `If-Match`, PUT override, `POST /zone-proposals/{id}/accept`).
  Cola worker `zoning`, servicio compose `worker-zoning`.
- **Acción**: incorporar `zone_proposals` a diseño §6.1 en la próxima revisión.
  No crear tarea WBS. No confundir propuesta con zona persistida.

### 3.13 Cohesión OSRM no está en el worker de propuestas

- **Estado**: 🟢 **Resuelto 2026-08-30** — 2.BE.7 `[x]`. `run_zone_proposal`
  hace clustering → `apply_cohesion` → fallback municipio/CP si
  `Router.table` falla.
- **Detectado**: 2026-08-30, al cerrar 2.BE.4.
- **Qué había**: [`cohesion.py`](../../backend/app/modules/zoning/cohesion.py)
  (`apply_cohesion`, `FakeRouter`, 11 tests). Baja la media intra-cluster;
  `max_visits` se mantiene; `table()` fallido conservaba la asignación
  original **sin** entrar al worker.
- **Qué faltaba**: el worker `zoning` paraba en features + `cluster_points`
  y serializaba ese resultado. Las propuestas HTTP no aplicaban la pasada
  viaria ni el fallback municipio/CP.
- **Cierre**: [`fallback.py`](../../backend/app/modules/zoning/fallback.py)
  + `_compute_proposal_result` / worker con `get_router()`. Si
  `Router.table` falla: agrupación por municipio/CP y split geodésico;
  métricas `fallback`. `FakeRouter` inyectado en e2e. Tests:
  [`test_zoning_fallback.py`](../../backend/tests/test_zoning_fallback.py)
  **11 passed**.

### 3.14 Publicar plan: 200 vs 202, outbox adelantado

- **Estado**: 🟡 Nota de consistencia (200 vs 202) — 2.BE.13 `[x]`. Consumidor
  outbox **4.BE.9 `[x]`**. **No** es un hueco del WBS de Fase 2.
- **Detectado**: 2026-08-30, al cerrar 2.BE.13.
- **200 vs 202**: `POST /api/v1/plans/{id}/publish` responde **200**. Diseño
  §8.4 / cola async sugería **202**. Una sola transacción confirma
  `monthly_plans.status=published` + filas `daily_routes` + `outbox_events`.
  Un 202 dejaría un worker que puede fallar después de marcar published.
  Tests: [`test_plan_publish_e2e.py`](../../backend/tests/test_plan_publish_e2e.py).
- **Outbox adelantado vs 4.BE.9**: Alembic `e4c8a2b91d07` creó
  `outbox_events` en 2.BE.13. **4.BE.9 `[x]` 2026-09-18** añadió
  `notifications` (Alembic `c4f1d82e90a3`) y el consumidor idempotente
  (`event_id`); no se duplicó la tabla.
- **Assignee por defecto**: `plan.created_by` (planner) salvo
  `body.assignees`. Rutas nacen `draft`. **3.BE.1 `[x]`** creó
  `route_revisions`/`route_stops`/`route_metrics`; publish de plan **no**
  crea revisión (optimize sí; 3.BE.11 `[x]` congela el snapshot).
- **Acción**: incorporar el 200 y `outbox_events` a diseño §6.1/§8.4 en la
  próxima revisión. No crear tarea WBS.

### 3.15 Publicar ruta: 200 vs 202

- **Estado**: 🟡 Nota de consistencia — 3.BE.11 `[x]`. **No** es un hueco del
  WBS de Fase 3.
- **Detectado**: 2026-09-11, al cerrar 3.BE.11.
- **200 vs 202**: `POST /api/v1/routes/{id}/publish` responde **200**. Diseño
  §8.5 no fija el código; §8.1 reserva 202 para trabajos largos. Publicar
  es sincrónico: snapshot cifrado + geometría OSRM + freeze de revisión
  en una transacción (ledger `route.publish`). Un 202 dejaría un worker
  que puede fallar después de marcar `published`. Mismo criterio que
  2.BE.13 / [§3.14](#314-publicar-plan-200-vs-202-outbox-adelantado).
- **Geometría**: se guarda en `route_revisions.constraints_json.snapshot`
  (GeoJSON LineString). No hay columna dedicada (diseño 6.1 no la tiene).
- **Acción**: incorporar el 200 a diseño §8.5 en la próxima revisión. No
  crear tarea WBS.

## 4. Infraestructura activa (estado real de la máquina de desarrollo)

Servicios `docker-compose` construidos y verificados en esta máquina de desarrollo:

| Servicio | Estado | Notas |
|---|---|---|
| `db` (PostgreSQL 17 + PostGIS) | ✅ Corriendo | Migraciones al día (`alembic upgrade head`) |
| `redis` | ✅ Corriendo | Cola de jobs (`imports`, `geocoding`, `zoning`, `planning`, `optimization`, ...) |
| `nominatim` | ✅ Corriendo | Extracto País Vasco importado (ver `scripts/infra/extracto-osm.md`) |
| `osrm` | ✅ Corriendo | Perfil `car.lua`, algoritmo MLD |
| `vault` | ✅ Corriendo | Modo dev (no apto para producción) |
| `minio` | Definido en compose 2026-08-30 | ObjectStore S3 (1.DATA.4). Credenciales de desarrollo |
| `api` (backend FastAPI) | ✅ Corriendo | Añadido a compose el 2026-08-30. Env S3 compartido con workers |
| `worker-imports` | Definido en compose 2026-08-30 | `python -m app.jobs.worker imports`. Misma imagen/env que `api` |
| `worker-geocoding` | Definido en compose 2026-08-30 | `python -m app.jobs.worker geocoding`. Misma imagen/env que `api` |
| `worker-zoning` | Definido en compose 2026-08-30 | `python -m app.jobs.worker zoning` (2.BE.5). Misma imagen/env que `api` |
| `worker-planning` | Definido en compose 2026-08-30 | `python -m app.jobs.worker planning` (2.BE.11). Misma imagen/env que `api` |
| `worker-optimization` | Definido en compose 2026-08-30 | `python -m app.jobs.worker optimization` (3.BE.7). Misma imagen/env que `api` |
| `frontend` (Nginx + build Vite) | ✅ Corriendo | Añadido a compose el 2026-08-30 |

CI (`.github/workflows/ci.yml`): lint+tests+build+escaneo Trivy para backend y frontend.

## 5. Cómo mantener este documento

Al terminar cualquier sesión de trabajo relevante (nueva fase, hallazgo, deuda técnica,
decisión aplazada):

1. Actualizar la tabla de la sección 2 si cambió el recuento de tareas por fase.
2. Añadir una entrada nueva en la sección 3 por cada deuda/decisión nueva (no reescribir
   el historial; marcar como resuelto lo que se cierre).
3. Actualizar la sección 4 si cambia la infraestructura activa.
4. Actualizar `Última actualización` y `Siguiente` en la cabecera.
5. Refrescar la [sección 6](#6-tareas-pendientes-índice-operativo) (índice de pendientes):
   desbloqueados, orden de Fase 2, recuentos e ids. Recalcular contra los checkboxes del
   WBS; no inventar IDs ni marcar 1.FE.8 hecha sin informe de usuarios reales.

## 6. Tareas pendientes (índice operativo)

Índice de las **41** `[ ]` del WBS a 2026-09-18. No sustituye criterios ni evidencia:
eso vive en [`tareas-app-rutas-pacientes.md`](../tareas/tareas-app-rutas-pacientes.md)
(§2.1 es el gemelo corto). Recuento por fase: [sección 2](#2-estado-por-fase).

**Siguiente corte de producto:** **4.BE.10** (`GET`/`PATCH` notificaciones). **1.FE.8**
sigue humana. Fase 3 **20/20**. Fase 4 **11/20**. **No** production-ready:
ClamAV, DoD PR, usabilidad.
**No** usar Fase 5 como camino principal. DoD de proceso (PR): [§3.9](#39-dod-general-no-cumplido-en-el-árbol-de-trabajo-actual) — no es una tarea WBS.

### 6.1 Ahora / desbloqueado

Tareas cuya `Depende de:` está toda `[x]` (o no tiene deps de tarea). Verificado contra el WBS el 2026-09-18.

| ID | Una línea | Tipo | Por qué ahora |
|---|---|---|---|
| 1.FE.8 | Usabilidad del asistente y el mapa con usuarios reales | humano | 1.FE.1 y 1.FE.4 `[x]`. Protocolo listo; **no** es el informe. **Siguiente humana.** |
| 4.BE.10 | `GET`/`PATCH` notificaciones in-app | código | 4.BE.9 `[x]`. **Siguiente código de producto.** |
| 4.BE.4 | Job de retención/purga + acta | código | 4.BE.1 y 0.DATA.4 `[x]`. Paralelo; no es el corte. |
| 5.SEC.7 | ClamAV en `POST /imports` | código | Deuda de 1.BE.1; 1.BE.1 `[x]`. Paralelo; no es el corte. |
| T.RGPD.1 | RAT y EIPD (asesoría jurídica) | jurídico | Sin deps de tarea. |
| T.CI.1 | CD a staging tras merge (migraciones + smoke) | código | 0.CI.1 `[x]`. Distinta de 0.CI.1/0.CI.2 (Fase 0, hechas). |
| T.CI.2 | Gate de cobertura que bloquea merge | código | 0.CI.1 `[x]`. |
| T.DOC.1 | OpenAPI del contrato (diseño §8) | docs | 1.BE.1 `[x]`. |
| T.DOC.2 | Guía de despliegue autoalojado + extracto OSM | docs | 0.DATA.5 `[x]`. |
| T.OBS.1 | Métricas de negocio y técnicas | código | 0.BE.6 `[x]`. |
| T.OBS.2 | Trazas OpenTelemetry API → job | código | 0.BE.1 `[x]`. |
| 4.BE.11 | `audit_events` append-only con hash encadenado | código | 0.DATA.2 `[x]`. Paralelo; no es el corte de producto. |
| 5.SEC.3 | Redacción de logs (sin PII) | código | 0.BE.7 `[x]`. Puede ir en paralelo; **no** es el corte. |
| 5.SEC.5 | MFA `admin`/`planner` + Argon2id | código | 0.BE.5 `[x]`. Puede ir en paralelo; **no** es el corte. |
| 5.SEC.6 | Adaptador de pago apagado por defecto | código | 0.BE.2 `[x]`. Puede ir en paralelo; **no** es el corte. |
| 5.DATA.1 | Backup PG diario + WAL/PITR cifrado | código | 0.DATA.1 `[x]`. Puede ir en paralelo; **no** es el corte. |
| 5.DATA.3 | 2 réplicas de API + health checks | código | 0.CI.2 `[x]`. Puede ir en paralelo; **no** es el corte. |
| 5.QA.1 | SAST + scan de deps/contenedores en CI | código | 0.CI.1 `[x]`. Puede ir en paralelo; **no** es el corte. |

5.SEC.4 tiene 0.DATA.4 `[x]` pero sigue anclada a diseño §4.1 (despliegue): no está en esta tabla.

### 6.2 Fase 2 (19/19) — hecha; pendientes: ninguna

Detalle y criterios: [WBS §6](../tareas/tareas-app-rutas-pacientes.md#6-fase-2--zonificación-y-planificación). 🔀 = marcada paralelizable en el WBS.

Dos cadenas desde 2.BE.1; 2.QA.1 cierra. **Hechas las 19.** Pendientes: ninguna.

**Zonificación:** 2.BE.1 `[x]` → 2.BE.2 `[x]` → 2.BE.3 `[x]` → (2.BE.4 `[x]` → 2.BE.7 `[x]` ∥ 2.BE.5 `[x]` → 2.BE.6 `[x]` → 2.FE.1 `[x]` → 2.FE.3 `[x]` ∥ 2.QA.2 `[x]`)

Cohesión OSRM **sí** cableada en `run_zone_proposal` (2.BE.7): clustering → `apply_cohesion` → fallback municipio/CP si `Router.table` falla. Ver [3.13](#313-cohesión-osrm-no-está-en-el-worker-de-propuestas) (resuelto).

**Planificación:** 2.BE.1 `[x]` → 2.BE.8 `[x]` → 2.BE.9 `[x]` → 2.BE.10 `[x]` → 2.BE.11 `[x]` → 2.BE.12 `[x]` → (2.BE.13 `[x]` → 2.BE.14 `[x]` ∥ 2.FE.2 `[x]`) → **2.QA.1 `[x]`**

| ID | Una línea | Paralelo |
|---|---|---|
| 2.BE.1 | Migraciones `zones` / `zone_assignments` | `[x]` Arranque (1.DATA.1 `[x]`) |
| 2.BE.2 | Features (densidad, urbano/rural, tiempo a depósito) | `[x]` Tras 2.BE.1; ∥ 2.BE.8 |
| 2.BE.8 | Migraciones `monthly_plans` / `daily_routes` | `[x]` Tras 2.BE.1; ∥ 2.BE.2 |
| 2.BE.3 | Clustering capacitado (K-means / HDBSCAN) | `[x]` Tras 2.BE.2 |
| 2.BE.4 | Cohesión viaria OSRM y bordes de zona | `[x]` Tras 2.BE.3. Cableada en el worker con 2.BE.7. |
| 2.BE.5 | Endpoints `POST/GET /zone-proposals` | `[x]` Tras 2.BE.3 |
| 2.QA.2 | Tests algorítmicos de clustering / `max_visits` | `[x]` Tras 2.BE.3 |
| 2.BE.7 | Fallback municipio/CP si falta OSRM | `[x]` Tras 2.BE.4. Worker: cohesión + fallback si falla `Router.table`. |
| 2.BE.6 | CRUD zonas y override de pacientes | `[x]` Tras 2.BE.5 |
| 2.FE.1 | Editor de zonas (propuesta, arrastrar, confirmar) | `[x]` Tras 2.BE.6. Vitest; sin Playwright. |
| 2.FE.3 | Distinción visual urbana/rural | `[x]` Tras 2.FE.1. `ZoneKindBadge` SVG + label + clase. |
| 2.BE.9 | Calendario laborable y capacidad diaria | `[x]` Tras 2.BE.8 |
| 2.BE.10 | Asignación diaria + conflictos | `[x]` Tras 2.BE.9 |
| 2.BE.11 | Endpoints de planes (crear/generar/validar) | `[x]` Tras 2.BE.10 |
| 2.BE.12 | Mover visita (`If-Match`) | `[x]` Tras 2.BE.11. Dry-run / confirm / `If-Match`. |
| 2.FE.2 | Calendario UI (drag + formulario) | `[x]` Tras 2.BE.12. Vitest; sin UI de publicar; sin Playwright. ∥ 2.BE.13 |
| 2.BE.13 | Publicar plan → `daily_routes` + outbox | `[x]` Tras 2.BE.12. HTTP **200** (no 202). Consumidor **4.BE.9 `[x]`**. |
| 2.BE.14 | Asignar visitador de campo | `[x]` Tras 2.BE.13. Otra org → 404. Mapa field/`visit_status` **no**. |
| 2.QA.1 | E2E zonas → ajustar → plan → publicar | `[x]` Cierre HTTP pytest; 200 pacientes; sin Playwright. |

### 6.2.1 Fase 3 (20/20) — hecha

Detalle y criterios: [WBS §7](../tareas/tareas-app-rutas-pacientes.md#7-fase-3--optimización-de-rutas). 🔀 = marcada paralelizable en el WBS.

**Hechas (20):** 3.BE.1–3.BE.14, 3.FE.1–3.FE.4, 3.QA.1, 3.QA.2.

**Pendientes (0).** Cierre: 3.QA.2 `[x]` 2026-09-11.

### 6.3 Resto por fase (recuento + ids)

Sin pegar criterios. Encabezados del WBS:

| Fase | Pendientes | Ids | WBS |
|---|---|---|---|
| 3 — Optimización | **20/20** hechas (**0** ids) | Fase cerrada. Hechas: 3.BE.1–3.BE.14, 3.FE.1–3.FE.4, 3.QA.1, 3.QA.2. | [§7](../tareas/tareas-app-rutas-pacientes.md#7-fase-3--optimización-de-rutas) |
| 4 — Histórico y colaboración | **11/20** hechas (**9** ids) | Hechas: 4.BE.1–4.BE.3, 4.BE.5–4.BE.9, 4.FE.1, 4.FE.2, 4.FE.5. Pendientes: 4.BE.4, 4.BE.10–4.BE.13, 4.FE.3–4.FE.4, 4.QA.1, 4.QA.2. **4.BE.10**, **4.BE.4** y **4.BE.11** también en 6.1. | [§8](../tareas/tareas-app-rutas-pacientes.md#8-fase-4--histórico-y-colaboración) |
| 5 — Seguridad y despliegue | 0/19; **7** en 6.1, **12** aquí | 5.SEC.1, 5.SEC.2, 5.SEC.4 (anclada a diseño 4.1), 5.DATA.2, 5.DATA.4, 5.DATA.5, 5.QA.2, 5.QA.3, 5.DEPLOY.1, 5.DEPLOY.2, 5.DEPLOY.3, 5.DEPLOY.4. 5.SEC.1 y 5.QA.2 piden fases 1–4 completas. | [§9](../tareas/tareas-app-rutas-pacientes.md#9-fase-5--pruebas-seguridad-y-despliegue) |
| Transversal | 0/12; **7** en 6.1, **5** aquí | T.OBS.3 (tras T.OBS.1), T.DOC.3 (fases 1–4 por rol), T.RGPD.2, T.RGPD.3, T.RGPD.4 (tras T.RGPD.1; 3 y 4 también 4.BE.4 / 5.SEC.6). | [§10](../tareas/tareas-app-rutas-pacientes.md#10-tareas-transversales) |

Fase 1 abierta: solo **1.FE.8** ([WBS §5](../tareas/tareas-app-rutas-pacientes.md#5-fase-1--mvp-importación-geocodificación-y-mapa)). Fase 0: 16/16.

### 6.4 DoD / proceso

El DoD general del WBS §3 (PR con segundo revisor, CI verde, etc.) **no** es una fila del WBS. Estado actual: [§3.9](#39-dod-general-no-cumplido-en-el-árbol-de-trabajo-actual). Las `[x]` de Fase 0/1/2/3 acreditan código y tests, no “listo para producción”.
