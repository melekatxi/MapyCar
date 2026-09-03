# Desglose de Tareas — App de Optimización de Rutas para Visitas a Pacientes

| Campo | Valor |
|---|---|
| Proyecto | App de Planificación y Optimización de Rutas de Visitas Domiciliarias |
| Versión | 1.0 |
| Fecha | 2026-08-30 |
| Estado | En ejecución — Fase 3 **iniciada 12/20**. Fase 2 19/19. Fase 1 código 27/28; único pendiente 1.FE.8 (humanos). 60 pendientes documentadas en §2.1 y [status §6](../info/status.md#6-tareas-pendientes-índice-operativo) |
| Requisitos base | [Requisitos de la aplicación](../requisitos/requisitos-app-rutas-pacientes.md) |
| Propuesta base | [Propuesta técnica y funcional](../propuesta/propuesta-app-rutas-pacientes.md) |
| Diseño base | [Diseño técnico](../diseno/diseno-app-rutas-pacientes.md) |

## 1. Cómo leer este documento

- Cada tarea sigue el formato `- [ ] {fase}.{área}.{n} Descripción`.
- `Ref:` indica el/los requisitos (RF-nn/RNF-nn) o la sección del diseño cubiertos.
- `Depende de:` indica tareas previas obligatorias (mismo documento).
- `Criterio:` indica la evidencia mínima de aceptación (test, endpoint, artefacto).
- Las tareas están agrupadas por área cuando aplica: **BE** (backend), **FE** (frontend), **DATA** (datos/infra), **SEC** (seguridad), **QA** (calidad).

## 2. Resumen de fases

| Fase | Nº tareas | Enfoque | Depende de |
|---|---|---|---|
| Fase 0 — Preparación | 16 | Infraestructura base, adaptadores, entorno dev/CI | — |
| Fase 1 — MVP importación/geocodificación/mapa | 28 | RF-01 a RF-08, RNF-01, RNF-07 a RNF-09 | Fase 0 |
| Fase 2 — Zonificación y planificación | 19 | RF-09 a RF-15 | Fase 1 |
| Fase 3 — Optimización de rutas | 20 | RF-16 a RF-22, RNF-02 | Fase 2 |
| Fase 4 — Histórico y colaboración | 20 | RF-23 a RF-30, RNF-11 | Fase 3 |
| Fase 5 — Pruebas, seguridad y despliegue | 19 | RNF-03 a RNF-06, RNF-10, despliegue en producción | Fase 4 (parcial en paralelo desde Fase 1) |
| Transversal | 12 | Observabilidad, CI/CD, documentación, RGPD | Se ejecuta en paralelo a todas las fases |
| **Total** | **134** | | |

## 2.1 Pendientes a 2026-08-30

Índice operativo de las **60** `[ ]`. Criterios y evidencia siguen en las secciones 4–10.
Gemelo más largo (resto por fase, DoD): [`docs/info/status.md` §6](../info/status.md#6-tareas-pendientes-índice-operativo).

Recuento: Fase 0 16/16; Fase 1 **27/28** (solo 1.FE.8); Fase 2 **19/19**; Fase 3 **12/20**; Fase 4 0/20; Fase 5 0/19; Transversal 0/12. Total **74/134**.

**Siguiente corte de producto:** **3.BE.11** (publish snapshot), **3.BE.9** (recalc), **3.FE.1** (UI) o **1.FE.8** (humanos). Fase 3 iniciada 12/20. **No** production-ready: ClamAV, DoD PR, usabilidad. Ledger Idempotency-Key = 3.BE.14 `[x]`. **No** arrancar Fase 5 como camino principal. DoD de proceso (PR): status [§3.9](../info/status.md#39-dod-general-no-cumplido-en-el-árbol-de-trabajo-actual) — no es una fila de este WBS.

### Ahora / desbloqueado

`Depende de:` toda `[x]` (verificado 2026-08-30). Las de Fase 5 / 4.BE.11 / deuda **pueden ir en paralelo; no son el corte**.

| ID | Una línea | Tipo | Por qué ahora |
|---|---|---|---|
| 1.FE.8 | Usabilidad del asistente y el mapa con usuarios reales | humano | 1.FE.1 y 1.FE.4 `[x]`. Protocolo ≠ informe. **Siguiente humana.** |
| 3.BE.11 | `POST /routes/{id}/publish` (snapshot inmutable) | código | 3.BE.7 `[x]`. **Siguiente código de producto.** Desbloquea 3.BE.13 / 3.FE.3 / 4.BE.1–2. |
| 3.BE.9 | Recalcular ruta al añadir/quitar/modificar paradas | código | 3.BE.7 `[x]`. Nueva clave de idempotencia por cambio. |
| 3.FE.1 | UI del optimizador (objetivo, origen, progreso) | código | 3.BE.7 `[x]`. |
| 3.FE.2 | Vista de diagnóstico e inviabilidad | código | 3.BE.12 `[x]`. |
| 4.BE.5 | Migración `share_grants` (CHECK sujeto XOR token) | código | 3.BE.1 `[x]`. Paralelo, no corte. |
| 5.SEC.7 | ClamAV en `POST /imports` | código | Deuda de 1.BE.1; 1.BE.1 `[x]`. |
| T.RGPD.1 | RAT y EIPD | jurídico | Sin deps de tarea. |
| T.CI.1 | CD a staging | código | 0.CI.1 `[x]`. |
| T.CI.2 | Gate de cobertura | código | 0.CI.1 `[x]`. |
| T.DOC.1 | OpenAPI | docs | 1.BE.1 `[x]`. |
| T.DOC.2 | Guía autoalojado | docs | 0.DATA.5 `[x]`. |
| T.OBS.1 | Métricas | código | 0.BE.6 `[x]`. |
| T.OBS.2 | Trazas OTel | código | 0.BE.1 `[x]`. |
| 4.BE.11 | `audit_events` append-only | código | 0.DATA.2 `[x]`. Paralelo, no corte. |
| 5.SEC.3 | Redacción de logs | código | 0.BE.7 `[x]`. Paralelo, no corte. |
| 5.SEC.5 | MFA + Argon2id | código | 0.BE.5 `[x]`. Paralelo, no corte. |
| 5.SEC.6 | Adaptador de pago apagado | código | 0.BE.2 `[x]`. Paralelo, no corte. |
| 5.DATA.1 | Backup PG + PITR | código | 0.DATA.1 `[x]`. Paralelo, no corte. |
| 5.DATA.3 | 2 réplicas API | código | 0.CI.2 `[x]`. Paralelo, no corte. |
| 5.QA.1 | SAST/scan en CI | código | 0.CI.1 `[x]`. Paralelo, no corte. |

### Fase 2 (19/19) — hecha; pendientes: ninguna

🔀 = paralelizable en el WBS. Cierre: 2.QA.1 `[x]`. **Hechas las 19.** Pendientes: ninguna.

**Zonificación:** 2.BE.1 `[x]` → 2.BE.2 `[x]` → 2.BE.3 `[x]` → (2.BE.4 `[x]` → 2.BE.7 `[x]` ∥ 2.BE.5 `[x]` → 2.BE.6 `[x]` → 2.FE.1 `[x]` → 2.FE.3 `[x]` ∥ 2.QA.2 `[x]`)

Cohesión OSRM **sí** cableada en `run_zone_proposal` (2.BE.7): clustering → `apply_cohesion` → fallback municipio/CP si `Router.table` falla. Ver [status §3.13](../info/status.md#313-cohesión-osrm-no-está-en-el-worker-de-propuestas) (resuelto).

**Planificación:** 2.BE.1 `[x]` → 2.BE.8 `[x]` → 2.BE.9 `[x]` → 2.BE.10 `[x]` → 2.BE.11 `[x]` → 2.BE.12 `[x]` → (2.BE.13 `[x]` → 2.BE.14 `[x]` ∥ 2.FE.2 `[x]`) → **2.QA.1 `[x]`**

| ID | Una línea | Paralelo |
|---|---|---|
| 2.BE.1 | Migraciones `zones` / `zone_assignments` | `[x]` Arranque |
| 2.BE.2 | Features densidad / urbano-rural | `[x]` Tras 2.BE.1; ∥ 2.BE.8 |
| 2.BE.8 | Migraciones `monthly_plans` / `daily_routes` | `[x]` Tras 2.BE.1; ∥ 2.BE.2 |
| 2.BE.3 | Clustering capacitado | `[x]` Tras 2.BE.2 |
| 2.BE.4 | Cohesión OSRM y bordes | `[x]` Tras 2.BE.3. Cableada en el worker con 2.BE.7. |
| 2.BE.5 | Endpoints `zone-proposals` | `[x]` Tras 2.BE.3 |
| 2.QA.2 | Tests de clustering | `[x]` Tras 2.BE.3 |
| 2.BE.7 | Fallback municipio/CP | `[x]` Tras 2.BE.4. Worker: cohesión + fallback si falla `Router.table`. |
| 2.BE.6 | CRUD zonas y override | `[x]` Tras 2.BE.5 |
| 2.FE.1 | Editor de zonas | `[x]` Tras 2.BE.6. Vitest; sin Playwright. |
| 2.FE.3 | Visual urbano/rural | `[x]` Tras 2.FE.1. `ZoneKindBadge` SVG + label + clase. |
| 2.BE.9 | Calendario y capacidad | `[x]` Tras 2.BE.8 |
| 2.BE.10 | Asignación diaria | `[x]` Tras 2.BE.9 |
| 2.BE.11 | Endpoints de planes | `[x]` Tras 2.BE.10 |
| 2.BE.12 | Mover visita | `[x]` Tras 2.BE.11. Dry-run / confirm / `If-Match`. |
| 2.FE.2 | Calendario UI | `[x]` Tras 2.BE.12. Vitest; sin UI de publicar; sin Playwright. ∥ 2.BE.13 |
| 2.BE.13 | Publicar plan | `[x]` Tras 2.BE.12. HTTP **200** (no 202). Outbox adelantado vs 4.BE.9. |
| 2.BE.14 | Asignar visitador | `[x]` Tras 2.BE.13. Otra org → 404. Mapa field/`visit_status` **no**. |
| 2.QA.1 | E2E zonas → plan → publicar | `[x]` Cierre HTTP pytest; 200 pacientes; sin Playwright. |

### Fase 3 (12/20) — iniciada

**Hechas (12):** 3.BE.1, 3.BE.14, 3.BE.2, 3.BE.3, 3.BE.4, 3.BE.5, 3.BE.6, 3.BE.7, 3.BE.8, 3.BE.10, 3.BE.12, 3.QA.1.

Cadena: 3.BE.1 `[x]` → 3.BE.2 `[x]` → (3.BE.3 `[x]` → 3.BE.4 `[x]` ∥ 3.BE.5 `[x]` ∥ 3.QA.1 `[x]` ; 3.BE.6 `[x]`) → 3.BE.7 `[x]` (ledger 3.BE.14 `[x]`). 3.BE.8 `[x]` tras 3.BE.6. 3.BE.10 `[x]` tras 3.BE.1. 3.BE.12 `[x]` tras 3.BE.4.

**Pendientes (8):** 3.BE.9, 3.BE.11, 3.FE.1 (deps 3.BE.7 — **en Ahora**); 3.FE.2 (deps 3.BE.12 — **en Ahora**); 3.BE.13 (espera 3.BE.11); 3.FE.3 (espera 3.BE.11); 3.FE.4 (espera 3.BE.13); 3.QA.2 (espera 3.BE.9 + 3.BE.11 + 3.BE.13).

Resto (ids, no criterios): Fase 3 [§7](#7-fase-3--optimización-de-rutas) (8 pendientes); Fase 4 [§8](#8-fase-4--histórico-y-colaboración) (20, 4.BE.5 y 4.BE.11 ya en “Ahora”); Fase 5 [§9](#9-fase-5--pruebas-seguridad-y-despliegue) (19, 7 ya en “Ahora”); Transversal [§10](#10-tareas-transversales) (12, 7 ya en “Ahora”). Lista completa de ids en [status §6.3](../info/status.md#63-resto-por-fase-recuento--ids).

## 3. Definition of Done general

Aplicable a toda tarea marcada como completada, salvo que se indique lo contrario en su criterio específico:

- [ ] Código con revisión (PR) aprobada por al menos una persona distinta del autor.
- [ ] Pruebas automatizadas relevantes (unitarias/integración/E2E según corresponda) en verde en CI.
- [ ] Sin secretos, direcciones ni datos de pacientes reales en código, logs o fixtures de prueba.
- [ ] Migraciones de base de datos reversibles y documentadas (si aplica).
- [ ] Documentación técnica (README/OpenAPI/comentario de módulo) actualizada si la tarea cambia un contrato público.
- [ ] Sin nuevas vulnerabilidades críticas/altas detectadas por el escaneo de dependencias/contenedores de CI.
- [ ] Cambios de UI verificados en desktop y en vista móvil/tablet cuando afecten a `Ruta de campo` o `Mapa operativo`.
- [ ] Evento de auditoría emitido para toda operación que cree, modifique, publique, comparta o borre datos de pacientes/rutas (cuando aplique según RF-30/RNF-11).

## 4. Fase 0 — Preparación

**Objetivo:** stack autoalojado, modelo de datos base, adaptadores y entorno de desarrollo/CI. Ref propuesta: sección 9 "Fase 0".

### DATA

- [x] 0.DATA.1 🔀 **[Paralelizable]** Crear `docker-compose.yml` de desarrollo con PostgreSQL 17 + PostGIS, Redis, Nominatim y OSRM con extracto de Euskadi/norte peninsular. Ref: ADR-04, ADR-05, ADR-07, sección 4.1. Criterio: `docker compose up` levanta los 4 servicios y responde `/status` en Nominatim y OSRM. **Verificado 2026-08-29**: los 5 servicios (db/redis/nominatim/osrm/vault) están arriba y `/status.php` (Nominatim) y `/route`+`/table` (OSRM) responden correctamente.
- [x] 0.DATA.2 🔀 **[Paralelizable]** Diseñar y crear migraciones iniciales (Alembic) para `organizations`, `users`, `user_memberships`, `teams`, `team_members`. Ref: sección 6.1. Depende de: 0.DATA.1. Criterio: `alembic upgrade head` crea las tablas con las restricciones UNIQUE/CHECK descritas. **Verificado**: `alembic upgrade head` aplicado contra la BD real, las 5 tablas existen.
- [x] 0.DATA.3 Habilitar Row Level Security (RLS) por `organization_id` en las tablas multi-tenant y añadir política de prueba de aislamiento. Ref: sección 9.1 (RLS), RNF-06. Depende de: 0.DATA.2. Criterio: test de integración demuestra que una sesión de la organización A no puede leer filas de la organización B. **Verificado**: RLS+FORCE activos en `teams`/`user_memberships` (comprobado en BD) y `test_identity_rls.py` en verde con Docker.
- [x] 0.DATA.4 🔀 **[Paralelizable]** Configurar KMS/Vault autoalojable para gestión de claves de cifrado por campo (AES-256-GCM) con versión de clave. Ref: sección 9.1, ADR-09. Criterio: cifrar/descifrar un valor de prueba usando la clave activa y rotar sin romper valores previos. **Verificado**: `test_crypto_vault.py` en verde con Docker (Vault real vía testcontainers).
- [x] 0.DATA.5 🔀 **[Paralelizable]** Importar extracto OSM en Nominatim y OSRM, documentar fecha/región/perfil usado. Ref: sección 4.1, 13.2. Depende de: 0.DATA.1. Criterio: smoke test geocodifica 5 municipios de referencia del dataset de Bizkaia. **Verificado 2026-08-29**: extracto de Geofabrik (País Vasco) importado en Nominatim y procesado en OSRM (perfil `car.lua`, algoritmo MLD); smoke test de Bilbao/Barakaldo/Getxo/Portugalete/Durango con coordenadas correctas. Documentación en [scripts/infra/extracto-osm.md](../../scripts/infra/extracto-osm.md).

### BE

- [x] 0.BE.1 🔀 **[Paralelizable]** Inicializar proyecto FastAPI modular con los límites de módulo `identity, imports, geocoding, zoning, planning, routing, optimization, history, sharing, notifications, audit, jobs`. Ref: ADR-01, sección 3.1. Criterio: estructura de carpetas compilable con un endpoint `GET /health` funcionando. **Verificado**.
- [x] 0.BE.2 🔀 **[Paralelizable]** Implementar interfaces de adaptador `Geocoder`, `Router`, `Optimizer`, `TileProvider`, `ObjectStore` con doble de prueba (fake) para tests. Ref: ADR-06, RNF-10. Depende de: 0.BE.1. Criterio: test unitario intercambia implementación real por fake sin cambiar el código que la consume. **Verificado**: `test_adapters.py` en verde.
- [x] 0.BE.3 🔀 **[Paralelizable]** Implementar adaptador Nominatim autoalojado (`Geocoder`) con `User-Agent`, caché y bounding box de Bizkaia/Euskadi configurables. Ref: ADR-07, sección 7.2. Depende de: 0.BE.2, 0.DATA.5. Criterio: test de contrato geocodifica una dirección de fixture y devuelve candidatos con score. **Verificado**: `test_adapters_contract.py` en verde + probado contra la instancia real (ver 0.DATA.5).
- [x] 0.BE.4 🔀 **[Paralelizable]** Implementar adaptador OSRM (`Router`) para `/table` y `/route`. Ref: ADR-07, sección 7.5. Depende de: 0.BE.2, 0.DATA.5. Criterio: test de contrato obtiene matriz NxN de tiempos/distancias sobre fixture de 5 puntos. **Verificado**: `test_adapters_contract.py` en verde + probado contra la instancia real (ver 0.DATA.5).
- [x] 0.BE.5 Implementar módulo `identity` (sesión, roles `admin/planner/field/supervisor`, autorización por organización). Ref: sección 9.1, RNF-06. Depende de: 0.DATA.2, 0.DATA.3. Criterio: test E2E de login y de rechazo 403 entre organizaciones. **Verificado**: `test_identity_e2e.py` en verde con Docker.
- [x] 0.BE.6 Configurar cola Redis con colas separadas (`imports, geocoding, zoning, routing, optimization, exports, notifications`) y worker base con reintentos/backoff. Ref: ADR-05, sección 11.2. Depende de: 0.DATA.1, 0.BE.1. Criterio: job de prueba encolado se ejecuta y su estado pasa `queued → running → succeeded`. **Verificado**: `test_jobs_queue.py` en verde.
- [x] 0.BE.7 🔀 **[Paralelizable]** Implementar modelo de error estándar (`type/title/status/code/detail/instance/request_id/errors`) y middleware de `X-Request-ID`. Ref: sección 8.1. Depende de: 0.BE.1. Criterio: cualquier error 4xx/5xx del API sigue el esquema documentado. **Verificado**: `test_errors.py` en verde.

### DevOps / CI-CD

- [x] 0.CI.1 🔀 **[Paralelizable]** Configurar pipeline CI (lint, tests unitarios, build de imágenes, escaneo de dependencias/contenedores). Ref: sección 4.1, DoD general. Criterio: pipeline en verde en un PR de ejemplo y falla si se introduce una vulnerabilidad crítica simulada. **Verificado**: [ci.yml](../../.github/workflows/ci.yml) con ruff+pytest+pip-audit+build+Trivy; `ruff check` y `pytest` reproducidos localmente en verde.
- [x] 0.CI.2 Publicar imágenes Docker fijadas por digest, usuario no root, filesystem de solo lectura donde sea viable. Ref: sección 4.1. Depende de: 0.CI.1. Criterio: `docker inspect` confirma usuario no root y digest fijo en el manifiesto. **Verificado**: [backend/Dockerfile](../../backend/Dockerfile) usa `FROM python@sha256:...` y `USER sofia` (uid 10001, no root).

### QA

- [x] 0.QA.1 🔀 **[Paralelizable]** Preparar dataset de pruebas a partir de `direcciones-ejemplo-bizkaia.csv` en formato CSV `;` y convertido a `.xlsx`. Ref: sección 12, anexo requisitos. Criterio: ambos ficheros se validan manualmente (acentos, pisos, CP repetidos) antes de usarse como fixture. **Aprobado 2026-08-29** por el responsable del proyecto, junto con la revisión de 0.QA.2 (incluyó corrección de 2 CP inconsistentes y regeneración de 13 direcciones rurales con nombres reales de OSM).
- [x] 0.QA.2 Definir "verdad de referencia" (ground truth) de geocodificación revisada manualmente sobre una muestra del dataset. Ref: sección 12, criterios de aceptación RF-05. Depende de: 0.QA.1. Criterio: documento de referencia con coordenadas validadas para al menos 30 direcciones (urbanas y rurales). **Aprobado 2026-08-29**: [ground-truth-geocoding-draft.md](../requisitos/ground-truth-geocoding-draft.md) revisado fila por fila y aprobado por el responsable del proyecto. El 24/30 (80%) de esa aprobación era first-hit de Nominatim **sin scorer** — no se reescribe como si ya cubriera RF-05. Se corrigieron 2 CP inconsistentes del fixture (PAC-005, PAC-012) durante la revisión. **Enmienda 2026-08-30 (opción 1)**: 4 portales que no existían en Eustat se sustituyen por portales oficiales (PAC-004 Zabalbide 90→92, PAC-005 Iturribide 55→54, PAC-010 Calle Kirikiño 3/48004→Avenida Kirikiño 2/48012, PAC-037 Bengoetxe 4→5). PAC-051 y PAC-058 siguen siendo el caso negativo ficticio. Matching RF-05: ver 1.DATA.3.

## 5. Fase 1 — MVP: Importación, geocodificación y mapa

**Objetivo:** RF-01 a RF-08, RNF-01, RNF-07, RNF-08, RNF-09. Ref propuesta: sección 9 "Fase 1".

### BE — Importación

- [x] 1.BE.1 Endpoint `POST /imports` (multipart + `Idempotency-Key`) con validación de MIME/firma real, tamaño y antivirus. Ref: RF-01, RF-04, sección 7.1, 8.3. Depende de: 0.BE.1, 0.BE.7. Criterio: subir `.xlsx` válido devuelve `202` con `job_id`; fichero con firma falsa devuelve `415`. **Implementado**: [app/modules/imports/router.py](../../backend/app/modules/imports/router.py) + [parsing.py](../../backend/app/modules/imports/parsing.py) (firma real por magic bytes). Antivirus real (ClamAV) **no** forma parte de esta tarea: queda en **5.SEC.7**. Idempotency-Key se exige (400 si falta); el ledger de payload/respuesta es **3.BE.14 `[x]`** (consumidor: `POST /routes/{id}/optimize`). La deduplicación de fichero/periodo de imports la da 1.BE.7.
- [x] 1.BE.2 Worker `validate_import`: parseo streaming, mapeo de columnas, normalización y staging en `import_rows`. Ref: RF-02, RF-04, sección 7.1. Depende de: 0.DATA.2, 0.BE.6, 1.BE.1. Criterio: fichero de 500 filas se procesa completo y deja conteos correctos en `import_batches.counts_json`. **Implementado**: `service.validate_import` + [app/jobs/worker.py](../../backend/app/jobs/worker.py) (runner real `python -m app.jobs.worker imports`). Verificado con test E2E (conteos `{total,valid,invalid}`).
- [x] 1.BE.3 🔀 **[Paralelizable]** Validaciones de fila: dirección/CP/municipio/provincia obligatorios, CP español de 5 dígitos, duplicados internos y contra periodo, longitud/caracteres, rechazo de macros/fórmulas peligrosas. Ref: RF-02. Depende de: 1.BE.2. Criterio: fixture con filas inválidas produce `errors_json` con código, campo y propuesta por fila. **Implementado**: [validation.py](../../backend/app/modules/imports/validation.py), 6 tests unitarios en verde.
- [x] 1.BE.4 🔀 **[Paralelizable]** Endpoint `GET /imports/{id}` y `GET /imports/{id}/rows?status=` con paginación por cursor. Ref: RF-02, sección 8.3. Depende de: 1.BE.2. Criterio: test de integración recupera progreso y filas filtradas por estado. **Implementado y verificado** (test E2E con Docker real).
- [x] 1.BE.5 Endpoint `PATCH /imports/{id}/rows/{row}` para corrección manual con control de versión. Ref: RF-03, sección 8.3. Depende de: 1.BE.3. Criterio: corregir una fila inválida la revalida y cambia su estado. **Implementado**: `import_rows` no está en la lista de recursos con `ETag`/`If-Match` de la sección 8.1 (esa exige versión solo en zonas/planes/rutas/paradas), así que no se añadió optimistic lock aquí; sí revalida y cambia el estado (verificado en test E2E).
- [x] 1.BE.6 Endpoint `POST /imports/{id}/commit` con upsert transaccional de `patients`/`addresses` (solo filas aceptadas explícitamente). Ref: RF-02, sección 5.1 (`ImportBatch`), 7.1. Depende de: 1.BE.3, 0.DATA.4. Criterio: commit parcial publica solo filas seleccionadas; el resto queda en staging. **Implementado y verificado**: upsert de `Patient`/`Address` con `address_ciphertext` cifrado (AES-256-GCM), commit parcial deja el resto en staging.
- [x] 1.BE.7 🔀 **[Paralelizable]** Deduplicación de carga por `file_sha256 + periodo + organization_id`. Ref: sección 6.1 (`import_batches`), 11.1. Depende de: 1.BE.1. Criterio: reenviar el mismo fichero/periodo sin flag de reimportación devuelve `409`. **Implementado y verificado**: índice único parcial + test E2E confirma `409 IMPORT_DUPLICATE`.

### BE — Geocodificación

- [x] 1.BE.8 Worker de geocodificación: normalización de dirección (Unicode, abreviaturas, piso/puerta) antes de consultar Nominatim. Ref: RF-05, sección 7.2. Depende de: 0.BE.3, 1.BE.6. Criterio: test unitario normaliza 10 direcciones de fixture sin alterar el original almacenado. **Implementado**: [normalization.py](../../backend/app/modules/geocoding/normalization.py); el original cifrado nunca se muta, solo se descifra a variable local para construir la consulta.
- [x] 1.BE.9 🔀 **[Paralelizable]** Caché de geocodificación por hash de dirección normalizada + versión de proveedor/dataset. Ref: sección 7.2, 11.5. Depende de: 1.BE.8. Criterio: segunda geocodificación de la misma dirección no llama a Nominatim (verificado por contador de llamadas en test). **Implementado**: [cache.py](../../backend/app/modules/geocoding/cache.py) sobre Redis (TTL 30 días); test verifica 1 sola llamada al geocodificador en dos geocodificaciones consecutivas.
- [x] 1.BE.10 🔀 **[Paralelizable]** Scoring de candidatos (calle/número, CP, municipio, provincia, clase, distancia) y clasificación `matched/ambiguous/not_found`. Ref: RF-05, sección 7.2. Depende de: 1.BE.8. Criterio original: sobre el ground truth de 0.QA.2, ≥95% de direcciones bien formateadas quedan `matched` correctamente. **Scorer implementado** ([scoring.py](../../backend/app/modules/geocoding/scoring.py)). **Al cierre de 1.BE.10 (2026-08-29)** el gate ≥95% **ya no era de esta tarea**; medición histórica en vivo: **15/28 (53.6%) `matched`**. Causa raíz en [geocoding-benchmark.md](../../scripts/qa/geocoding-benchmark.md): cobertura incompleta de números de portal en el extracto OSM, no un fallo del scorer. **Dueño del SLO ≥95%: 1.DATA.3** (decisión de producto: mapear/enriquecer OSM; no relajar el SLO ni contratar geocodificador de pago) — **cerrado 2026-08-30** ([x], **28/28**). Este párrafo no contradice 1.DATA.3.
- [x] 1.BE.11 🔀 **[Paralelizable]** Endpoint `POST /imports/{id}/geocode` (encola geocodificación de filas elegibles). Ref: RF-05, sección 8.3. Depende de: 1.BE.10. Criterio: job procesa el lote y actualiza `geocode_status` por dirección. **Implementado y verificado** con test E2E (Docker real).
- [x] 1.BE.12 🔀 **[Paralelizable]** Endpoints `GET /addresses/{id}/candidates` y `POST /addresses/{id}/geocode-selection` (elegir candidato o fijar marcador manual). Ref: RF-03, sección 7.2, 8.3. Depende de: 1.BE.10. Criterio: seleccionar candidato o coordenada manual marca la dirección como confirmada y registra auditoría con motivo. **Implementado**: motivo y revisor se guardan en `geocode_attempts` (outcome `manual`); la auditoría completa con hash encadenado es RF-30/Fase 4, fuera de alcance aquí.
- [x] 1.BE.13 🔀 **[Paralelizable]** Fallback de geocodificación: reintento exponencial ante 429/5xx, simplificación de piso/portal, búsqueda por CP+municipio. Ref: sección 7.2. Depende de: 1.BE.10. Criterio: test simula 429 de Nominatim y confirma reintento con backoff antes de marcar `not_found`. **Implementado y verificado**: test con geocodificador que falla con 429 en el primer intento y responde en el segundo.
- [x] 1.BE.14 Cumplir RNF-01: lote de 200 direcciones geocodificado en menos de 5 minutos contra instancia propia. Ref: RNF-01, sección 11.3 (SLO). Depende de: 1.BE.9, 1.BE.11. Criterio: prueba de rendimiento documentada con hardware de referencia. **Cumplido con amplio margen**: 120 direcciones reales geocodificadas en 22.0 s contra la instancia propia → proyección de ~36.7 s para 200 (límite: 300 s). Documentado en [geocoding-benchmark.md](../../scripts/qa/geocoding-benchmark.md).

### FE

- [x] 1.FE.1 🔀 **[Paralelizable]** Asistente de importación: carga de fichero, selección de periodo/equipo, mapeo de columnas. Ref: RF-01, sección 3.2. Depende de: 1.BE.1. Criterio: flujo E2E sube `.xlsx` y muestra `job_id`/progreso. **Implementado**: [ImportWizardPage.tsx](../../frontend/src/imports/ImportWizardPage.tsx) (React+TS+Vite, proyecto nuevo en `frontend/`). Mapeo de columnas usa las cabeceras canónicas del backend por defecto; selección de equipo queda pendiente de que exista el modelo `teams` operativo en planificación (Fase 2).
- [x] 1.FE.2 Vista de progreso y tabla de errores descargable con reanudación. Ref: RF-02, sección 3.2. Depende de: 1.BE.4. Criterio: E2E muestra filas con error y permite descargar CSV de errores. **Implementado**: [ImportProgressPage.tsx](../../frontend/src/imports/ImportProgressPage.tsx) con polling de estado, tabla de errores, corrección en línea y descarga CSV client-side.
- [x] 1.FE.3 Bandeja de geocodificación: candidatos, confianza, mapa de confirmación, edición textual y colocación manual del marcador. Ref: RF-03, sección 3.2. Depende de: 1.BE.12. Criterio: E2E selecciona candidato y confirma dirección con auditoría visible. **Implementado**: [GeocodingTrayPage.tsx](../../frontend/src/geocoding/GeocodingTrayPage.tsx) con mapa Leaflet de candidatos y colocación manual por clic; motivo obligatorio se envía al backend (queda en `geocode_attempts`). Auditoría completa (RF-30) es Fase 4.
- [x] 1.FE.4 Mapa operativo con Leaflet + teselas OSM: capas de pacientes, zoom/desplazamiento. Ref: RF-06, ADR-02. Depende de: 1.BE.6. Criterio: E2E carga N puntos geocodificados en el mapa. **Implementado**: [OperationalMapPage.tsx](../../frontend/src/map/OperationalMapPage.tsx) consume `GET /patients` (nuevo endpoint de apoyo, no documentado explícitamente en la sección 8.3 original pero necesario para pintar el mapa).
- [x] 1.FE.5 Distinción visual por zona/estado (color/icono: pendiente, planificada, completada). Ref: RF-07. Depende de: 1.FE.4. Criterio: captura de regresión visual confirma leyenda y colores por estado. **Cerrado 2026-08-30 como MVP de RF-07**: leyenda de visita pendiente/planificada/completada; marcadores coloreados por `visit_status` (relleno) y geocodificación (borde, segunda leyenda). Hoy todos los pacientes llegan `visit_status=pending`. Comprobaciones visuales en Vitest [`OperationalMapPage.test.tsx`](../../frontend/src/map/OperationalMapPage.test.tsx). **Caveat residual:** 2.BE.14 `[x]` cerró assignee HTTP (otra org 404); **no** alimentó `visit_status` planned/completed en el mapa. No hay fila WBS nueva.
- [x] 1.FE.6 Detalle de punto al seleccionarlo (paciente, dirección, día/zona asignada) respetando permisos por rol. Ref: RF-08, sección 9.1 (RBAC). Depende de: 1.FE.4, 0.BE.5. Criterio original (field solo ve rutas asignadas) era **sobre-especificación** frente a RF-08 (detalle al seleccionar: paciente/ref, dirección minimizada, día/zona). **Cerrado 2026-08-30 contra RF-08**: [`PatientDetailPanel.tsx`](../../frontend/src/map/PatientDetailPanel.tsx) muestra referencia, municipio/CP/provincia, confianza, estado de visita y día/zona = **Sin asignar**. Nunca el nombre real ni la calle (ADR-09). Tests en [`PatientDetailPanel.test.tsx`](../../frontend/src/map/PatientDetailPanel.test.tsx). El filtro field-only **no existe** y no se afirma: 2.BE.14 `[x]` no lo añadió (`GET /patients` sigue sin filtrar); `ShareGrant` es Fase 4.
- [x] 1.FE.7 🔀 **[Paralelizable]** Adaptar UI a desktop y móvil/tablet (responsive). Ref: RNF-08. Depende de: 1.FE.1, 1.FE.4. Criterio: E2E ejecutado en viewport desktop y móvil sin romper flujo de importación/mapa. **Implementado**: breakpoint `@media (max-width: 768px)` en [index.css](../../frontend/src/index.css) colapsa la navegación y pasa los layouts de mapa/bandeja a una columna.
- [ ] 1.FE.8 🔀 **[Paralelizable]** Pruebas de usabilidad guiada con usuarios no técnicos sobre el asistente de importación y el mapa. Ref: RNF-07. Depende de: 1.FE.1, 1.FE.4. Criterio: informe de usabilidad con hallazgos y ≤2 bloqueantes críticos sin resolver. **Sigue abierta.** Protocolo (≠ informe): [`docs/qa/usabilidad-fase1-protocolo.md`](../qa/usabilidad-fase1-protocolo.md). No se cierra sin usuarios reales ni al publicar el protocolo.

### DATA

- [x] 1.DATA.1 Migraciones para `import_batches`, `import_rows`, `patients`, `addresses`, `geocode_attempts` con índices GiST/B-tree descritos. Ref: sección 6.1, 6.2. Depende de: 0.DATA.2. Criterio: `alembic upgrade head` crea tablas e índices; test de integración verifica unicidad `(organization_id, external_ref)`. **Verificado 2026-08-29** contra la BD real (`alembic upgrade head` en verde) + RLS añadida en `import_batches`/`patients`/`addresses` (test dedicado en `test_imports_rls.py`, mismo patrón que 0.DATA.3). `import_rows`/`geocode_attempts` no tienen `organization_id` propio (así lo define el diseño); su aislamiento se aplica siempre uniendo con `import_batches`/`addresses` en la capa de servicio.
- [x] 1.DATA.2 Cifrado por campo de `address_ciphertext` y `raw_json_encrypted` con AES-256-GCM. Ref: ADR-09, sección 9.1. Depende de: 0.DATA.4, 1.DATA.1. Criterio: dato en BD no legible sin la clave activa (verificado por consulta directa en test). **Implementado**: reutiliza `FieldCipher` de 0.DATA.4.
- [x] 1.DATA.3 Enriquecer cobertura de números de portal en el extracto OSM/Nominatim de la zona piloto (Bizkaia) con fuente independiente (Catastro/Cartociudad o mapeo OSM real). Ref: RF-05, hallazgo 3.1 de [`docs/info/status.md`](../info/status.md). Depende de: 0.DATA.5, 1.BE.10, 0.QA.2. Criterio: re-ejecutar el benchmark de [`scripts/qa/geocoding-benchmark.md`](../../scripts/qa/geocoding-benchmark.md) contra el ground truth de 0.QA.2 y alcanzar ≥95% `matched` en direcciones bien formateadas. **Notas**: no insertar las coordenadas del ground truth en el matcher (sería circular). Caseríos rurales sin centro OSM pueden limitar el techo — documentar excepciones. **Dueño del gate ≥95% de RF-05** (1.BE.10 queda como scorer implementado). **Hecho 2026-08-30**: Nominatim local + scorer + overlay: **28/28 (100%) `matched`** (antes 15/28 = 53.6% → overlay 24/28 = 85.7% → GT opción 1). Las 4 filas siguen en el denominador. Sustituciones oficiales: PAC-004 Zabalbide 90→92 (OSM ya tiene el 92), PAC-005 Iturribide 55→54 (OSM tiene el 54), PAC-010 Calle Kirikiño 3/48004→Avenida Kirikiño 2/48012 (OSM tiene el 2; «Calle» devolvía 0), PAC-037 Bengoetxe 4→5 (overlay Eustat; OSM no tiene el housenumber). Overlay: `backend/app/modules/geocoding/overlay.py` + `data/housenumber_overlay.csv`. Nominatim primario. No se volcó Eustat a OSM.org. No se inventaron 90/55/3/4. `augment` ignora un portal homónimo en otra vía (Olabarrieta 5 ≠ Bengoetxe 5). Ver status 3.1 (resuelto) y 3.10 (resuelto).
- [x] 1.DATA.4 Adaptador ObjectStore real S3-compatible cifrado (no `InMemoryObjectStore` en el camino de la API). Ref: diseño sección 4, ADR-06. Depende de: 0.BE.2, 1.BE.1. Criterio: fichero subido en `POST /imports` sobrevive un reinicio del proceso API; tests de contrato del adaptador real. **Hecho 2026-08-30**: [`S3ObjectStore`](../../backend/app/adapters/object_store/s3.py) cifra AES-GCM (`ObjectCipher`) antes de MinIO; `get_object_store()` usa S3 si hay `SOFIA_S3_ENDPOINT_URL`. MinIO en compose; workers `worker-imports` / `worker-geocoding` copian el mismo env S3 (sin eso el worker cae en InMemory y no ve uploads de la API). Tests [`test_object_store_s3.py`](../../backend/tests/test_object_store_s3.py): roundtrip con nueva instancia (reinicio) y at-rest ≠ plaintext. Los e2e HTTP siguen con override `InMemoryObjectStore`.

### QA

- [x] 1.QA.1 Suite E2E: importar → corregir → geocodificar → ver en mapa, sobre dataset ficticio de Bizkaia. Ref: RF-01 a RF-08, sección 12. Depende de: 1.BE.6, 1.BE.12, 1.FE.6. Criterio: escenario completo en verde en CI con datos ficticios. **Hecho 2026-08-30**: E2E HTTP en CI `backend/tests/test_import_geocode_map_e2e.py` (planner, slice ficticio de 3 filas, CP correcto, commit, geocode con Nominatim fake, `GET /patients`). Tests Vitest de wizard/progreso/mapa (Leaflet mockeado). `pytest` 11 passed incluyendo este fichero + e2e relacionados; `npm run test` 6 passed. CI ya ejecuta pytest y npm test — no hace falta cambiar el workflow. **Caveat**: no hay Playwright; zoom/pan de Leaflet no está en CI. 1.FE.6 se cierra contra RF-08 (detalle); field-RBAC **no** se afirma. Datos reales planned/completed de RF-07 **no** se cerraron con 2.BE.14 (mapa sigue `pending`).
- [x] 1.QA.2 🔀 **[Paralelizable]** Pruebas de formatos de importación: `.xlsx`, `.xls`, CSV `;` y CSV `,`. Ref: RNF-09. Depende de: 1.BE.2. Criterio: los 4 formatos de fixture se importan correctamente. **Hecho 2026-08-30**: `xlrd` 2.0.2, `detect_format`/`parse_rows` para `.xls` (magic OLE2 `D0 CF 11 E0`); tests `test_imports_parsing` + e2e upload 202. 22 parsing/validation passed, 3 e2e xls passed, ruff limpio. Residual de UI cerrado 2026-08-30: `ImportWizard` `accept=".csv,.xlsx,.xls"`.

## 6. Fase 2 — Zonificación y planificación

**Objetivo:** RF-09 a RF-15. Ref propuesta: sección 9 "Fase 2".

### BE — Zonificación

- [x] 2.BE.1 Migraciones para `zones`, `zone_assignments` con geometría PostGIS e índices GiST. Ref: sección 6.1, 6.2. Depende de: 1.DATA.1. Criterio: `alembic upgrade head` crea tablas; UNIQUE `(organization_id, name)` verificado en test. **Hecho 2026-08-30**: Alembic `7f30767de9b7`. UNIQUE `(organization_id, name)`, CHECK `kind IN ('urban','rural','mixed')`, GiST en `boundary`/`centroid`, RLS ENABLE+FORCE. `zone_assignments` incluye `organization_id` (el diseño 6.1 lo omitió en la lista de columnas) y FK compuestas a `zones`/`patients`. UNIQUE de apoyo `patients (id, organization_id)` (`uq_patients_id_org`). Tests: [`test_zoning_schema.py`](../../backend/tests/test_zoning_schema.py) + [`test_zoning_rls.py`](../../backend/tests/test_zoning_rls.py) **10 passed**.
- [x] 2.BE.2 Generación de features de zonificación (coordenadas proyectadas, densidad, tipo urbano/rural, tiempo aproximado al depósito). Ref: RF-12, sección 7.3. Depende de: 1.BE.10, 2.BE.1. Criterio: test unitario calcula features sobre fixture con puntos urbanos y rurales. **Hecho 2026-08-30**: [`features.py`](../../backend/app/modules/zoning/features.py). EPSG:25830, densidad, urbano/rural, minutos al depósito por haversine (**no** OSRM; la matriz viaria es 2.BE.4). Tests: [`test_zoning_features.py`](../../backend/tests/test_zoning_features.py) **7 passed**.
- [x] 2.BE.3 Clustering capacitado (K-means capacitado para zonas densas; jerárquico/DBSCAN-HDBSCAN para zonas rurales/outliers). Ref: RF-09, RF-11, RF-12, sección 7.3. Depende de: 2.BE.2. Criterio: prueba algorítmica sobre dataset ficticio respeta `max_visits` configurado. **Hecho 2026-08-30**: [`clustering.py`](../../backend/app/modules/zoning/clustering.py). Urbano: K-means capacitado + semillas municipio/CP. Rural: DBSCAN + outliers. `max_visits` nunca se excede. sklearn. Tests: [`test_zoning_clustering.py`](../../backend/tests/test_zoning_clustering.py) **9 passed** (16 con features). Los casos sintéticos con óptimo conocido y semilla fija son **2.QA.2** `[x]`.
- [x] 2.BE.4 Segunda pasada de cohesión con distancia viaria OSRM y ajuste de bordes de zona. Ref: sección 7.3, ADR-10. Depende de: 0.BE.4, 2.BE.3. Criterio: test compara dispersión en minutos antes/después del ajuste. **Hecho 2026-08-30**: [`cohesion.py`](../../backend/app/modules/zoning/cohesion.py). `apply_cohesion` con `FakeRouter`; baja la media intra-cluster en minutos; `max_visits` se mantiene; si `table()` falla se conserva la asignación original. Tests: [`test_zoning_cohesion.py`](../../backend/tests/test_zoning_cohesion.py) **11 passed**. Cableada en `run_zone_proposal` el mismo día con **2.BE.7** (clustering → `apply_cohesion` → fallback si `Router.table` falla).
- [x] 2.BE.5 🔀 **[Paralelizable]** Endpoint `POST /zone-proposals` y `GET /zone-proposals/{id}` (zonas, asignaciones, outliers, métricas). Ref: RF-09, sección 8.4. Depende de: 2.BE.3. Criterio: job de propuesta devuelve zonas y outliers consultables. **Hecho 2026-08-30**: `POST /api/v1/zone-proposals` 202 + GET. Tabla `zone_proposals` (no está en diseño 6.1; recurso 8.4). Alembic `c8e41f7a02b3` revises `bdf038e859a7`. Cola worker `zoning`, compose `worker-zoning`. GET 409 si la propuesta no está lista. Solo geocodes confirmados `matched`/`manual`. E2E 21 passed junto con otros tests de zoning. Las assignments del GET son ids de cluster de la propuesta, **no** filas de `zone_assignments` (persistir zonas reales = **2.BE.6** `[x]`).
- [x] 2.BE.6 Endpoints `POST /zones`, `PATCH /zones/{id}`, `PUT /zones/{id}/patients/{patientId}` (override manual con `If-Match`/motivo). Ref: RF-10, sección 8.4. Depende de: 2.BE.5. Criterio: reasignar manualmente un paciente persiste tras regenerar propuesta, salvo reseteo explícito. **Hecho 2026-08-30**: `POST /api/v1/zones` 201, `PATCH` con `If-Match`, `PUT /zones/{id}/patients/{patientId}` (override), `POST /zone-proposals/{id}/accept`. El override manual sobrevive a accept salvo `reset_overrides=true`. Tests: [`test_zones_e2e.py`](../../backend/tests/test_zones_e2e.py) + suite zoning **23 passed**.
- [x] 2.BE.7 Fallback de zonificación por municipio/CP y distancia geodésica si faltan matrices OSRM. Ref: sección 7.3. Depende de: 2.BE.4. Criterio: test simula OSRM caído y confirma agrupación por municipio/CP. **Hecho 2026-08-30**: [`fallback.py`](../../backend/app/modules/zoning/fallback.py). Worker: clustering → `apply_cohesion` → `fallback_group` si `Router.table` falla (municipio/CP + split geodésico). Métricas `fallback`. Tests: [`test_zoning_fallback.py`](../../backend/tests/test_zoning_fallback.py) **11 passed**. Worker pasa `get_router()`; `FakeRouter` inyectado en e2e. Cierra el cableado de cohesión en `run_zone_proposal` ([status §3.13](../info/status.md#313-cohesión-osrm-no-está-en-el-worker-de-propuestas)).

### BE — Planificación

- [x] 2.BE.8 Migraciones para `monthly_plans`, `daily_routes` (sin `route_revisions` aún). Ref: sección 6.1. Depende de: 2.BE.1. Criterio: `alembic upgrade head` aplica UNIQUE `(organization_id, team_id, period, version)`. **Hecho 2026-08-30**: Alembic `bdf038e859a7` (revises `7f30767de9b7`). UNIQUE `(organization_id, team_id, period, version)`. RLS ENABLE+FORCE. Estados según diseño §5.1: planes `draft/validating/published/archived` (**no** `validated`; eso es `ImportBatch`); rutas `draft/optimizing/ready/published/in_progress/completed/cancelled`. UNIQUE de apoyo `teams (id, organization_id)` (`uq_teams_id_org`). Tests: [`test_planning_schema.py`](../../backend/tests/test_planning_schema.py) + [`test_planning_rls.py`](../../backend/tests/test_planning_rls.py) **13 passed**.
- [x] 2.BE.9 Cálculo de calendario laborable y capacidad diaria (máximo de visitas, duración de servicio, jornada, tipo de zona, ventanas). Ref: RF-13, sección 7.4. Depende de: 2.BE.8. Criterio: test unitario genera calendario mensual respetando festivos configurados. **Hecho 2026-08-30**: [`calendar.py`](../../backend/app/modules/planning/calendar.py). Festivos vía config, `Europe/Madrid`, buffer de servicio rural +15 min. Tests: [`test_planning_calendar.py`](../../backend/tests/test_planning_calendar.py) **9 passed**.
- [x] 2.BE.10 Algoritmo de asignación diaria priorizando ventana estrecha/zona rural, con validación de conflictos (duplicado, visitador no disponible, ventana fuera de jornada, capacidad excedida, dirección no confirmada). Ref: RF-13, sección 7.4. Depende de: 2.BE.9. Criterio: test genera plan mensual sin conflictos sobre dataset de 200 pacientes ficticios. **Hecho 2026-08-30**: [`assignment.py`](../../backend/app/modules/planning/assignment.py). 200 pacientes ficticios Sep 2026: 190 asignados, 10 `ADDRESS_NOT_CONFIRMED`, cero conflictos en los asignados. Tests: [`test_planning_assignment.py`](../../backend/tests/test_planning_assignment.py) **18 passed**. HTTP de planes = **2.BE.11** `[x]`.
- [x] 2.BE.11 Endpoints `POST /plans`, `POST /plans/{id}/generate`, `GET /plans/{id}`, `POST /plans/{id}/validate`. Ref: RF-13, sección 8.4. Depende de: 2.BE.10. Criterio: E2E crea plan borrador y genera calendario con conflictos reportados si existen. **Hecho 2026-08-30**: `POST /api/v1/plans` 201; `POST .../generate` 202 cola `planning`; GET; `POST .../validate`. Alembic `024e6184b61b` revises `c8e41f7a02b3` (`result_json`, `conflicts_json`, `job_id`). Compose `worker-planning`. Field → 403. Dirección no confirmada → `ADDRESS_NOT_CONFIRMED`. pytest **199 passed** incluyendo [`test_plans_e2e.py`](../../backend/tests/test_plans_e2e.py).
- [x] 2.BE.12 Endpoint `PATCH /plans/{id}/visits/{patientId}` (mover visita manualmente) con `If-Match` y comando versionado. Ref: RF-14, sección 7.4. Depende de: 2.BE.11. Criterio: mover una visita devuelve conflictos antes de confirmar y aplica cambio si no hay conflicto. **Hecho 2026-08-30**: `PATCH /api/v1/plans/{id}/visits/{patientId}` con `If-Match`. Dry-run (`confirm` omitido) → 200 con conflictos, **sin** mutar. `confirm=true` + conflictos vacíos → aplica y `version++`. `confirm=true` + conflictos → 409 `PLAN_MOVE_CONFLICT`. Tests: [`test_plans_e2e.py`](../../backend/tests/test_plans_e2e.py); **55 planning tests passed**.
- [x] 2.BE.13 Endpoint `POST /plans/{id}/publish`: bloquea versión, crea `daily_routes`/revisión inicial y notifica vía outbox. Ref: RF-15, sección 7.4, 11.1 (outbox). Depende de: 2.BE.12, 0.BE.6. Criterio: publicar un plan crea rutas diarias con visitador asignado y evento de notificación transaccional. **Hecho 2026-08-30**: `POST /api/v1/plans/{id}/publish` **200** (no 202: una transacción confirma plan + `daily_routes` + outbox; un 202 dejaría un worker posterior al commit). Alembic [`e4c8a2b91d07`](../../backend/alembic/versions/e4c8a2b91d07_outbox_events.py) (`outbox_events`). Evento `plan.published`, `processed_at` nulo. Assignee por defecto = `plan.created_by` (planner) salvo `body.assignees`. Rutas nacen `draft` (sin revisión hasta 3.BE.11; tablas 3.BE.1 `[x]`). Tests: [`test_plan_publish_e2e.py`](../../backend/tests/test_plan_publish_e2e.py). **Caveats**: diseño pedía 202; tabla outbox adelantada vs consumidor 4.BE.9. Ver [status §3.14](../info/status.md#314-publicar-plan-200-vs-202-outbox-adelantado).
- [x] 2.BE.14 Asignación de ruta diaria a un usuario de campo concreto con verificación de rol/organización. Ref: RF-15. Depende de: 2.BE.13, 0.BE.5. Criterio: asignar a un usuario fuera de la organización devuelve 403/404. **Hecho 2026-08-30**: `PUT /api/v1/plans/{id}/routes/{routeId}/assignee` + `GET /plans/{id}/routes`. Usuario de otra org → **404** (criterio 403/404 cumplido). Tests en [`test_plan_publish_e2e.py`](../../backend/tests/test_plan_publish_e2e.py) (`test_assign_field_user_and_foreign_404`). **Caveat (seguimiento mapa Fase 1, no cerrado aquí):** `GET /patients` / mapa **no** filtran el rol `field` a rutas asignadas ni alimentan `visit_status` planned/completed reales. Las leyendas de 1.FE.5 siguen con todos `pending`. No hay fila WBS nueva. Ver [status §3.6](../info/status.md#36-restricciones-por-rol-y-estados-de-ruta-pendientes-de-fase-234).

### FE

- [x] 2.FE.1 Editor de zonas: parámetros, propuesta, arrastrar/reasignar, capacidad y confirmación versionada. Ref: RF-09, RF-10, RF-11, sección 3.2. Depende de: 2.BE.6. Criterio: E2E arrastra un paciente entre zonas y confirma con motivo. **Hecho 2026-08-30**: ruta `/zonas` [`ZoneEditorPage.tsx`](../../frontend/src/zoning/ZoneEditorPage.tsx). Poll de propuesta, accept, drag HTML5 en list-item + alternativa de formulario, motivo obligatorio, PUT `If-Match`. Backend: `GET /zones` lista; `GET /patients` incluye `zone_id`. Vitest **15 passed**; backend zones/patients **8 passed**. **Caveat**: no hay Playwright (igual que 1.QA.1). Iconografía urbana/rural = **2.FE.3** `[x]`.
- [x] 2.FE.2 Calendario mensual/diario con capacidad, conflictos, asignación de visitador; drag-and-drop accesible con alternativa de formulario. Ref: RF-13, RF-14, RF-15, RNF-07. Depende de: 2.BE.12. Criterio: E2E mueve visita por drag-and-drop y por formulario alternativo, ambos con el mismo resultado. **Hecho 2026-08-30**: ruta `/planificacion` [`PlanCalendarPage.tsx`](../../frontend/src/planning/PlanCalendarPage.tsx). Drag HTML5 + formulario; ambos dry-run luego confirm (`If-Match`). `GET /teams`, `GET /plans`. Vitest **30 passed**. **Caveats**: sin UI de publicar; sin Playwright (igual que 2.FE.1 / 1.QA.1).
- [x] 2.FE.3 Distinción visual urbana/rural en editor de zonas y calendario. Ref: RF-12. Depende de: 2.FE.1. Criterio: revisión visual confirma iconografía diferenciada por tipo de zona. **Hecho 2026-08-30**: [`ZoneKindBadge.tsx`](../../frontend/src/zoning/ZoneKindBadge.tsx) urban/rural/mixed (SVG + label + clase `zone-kind--*`). Editor de zonas + chips del calendario. Tests planning+zoning **18**.

### QA

- [x] 2.QA.1 Suite E2E: proponer zonas → ajustar manualmente → generar plan mensual → publicar. Ref: RF-09 a RF-15, sección 12. Depende de: 2.BE.13, 2.FE.2. Criterio: escenario completo en verde en CI con dataset ficticio de 200 pacientes. **Hecho 2026-08-30**: [`test_fase2_e2e.py`](../../backend/tests/test_fase2_e2e.py) 200 pacientes ficticios; proposal → override → plan generate → move → publish. **1 passed** ~8 s. HTTP pytest (testcontainers), **no** Playwright.
- [x] 2.QA.2 🔀 **[Paralelizable]** Pruebas algorítmicas de clustering con casos rurales/urbanos y verificación de `max_visits`. Ref: RF-11, RF-12, sección 12. Depende de: 2.BE.3. Criterio: casos sintéticos con óptimo conocido y semilla fija pasan en CI. **Hecho 2026-08-30**: [`test_zoning_clustering_qa.py`](../../backend/tests/test_zoning_clustering_qa.py) **5 passed**, `seed=0`, blobs con óptimo conocido. Los 9 tests de 2.BE.3 no cierran esta tarea; esta suite sí.

## 7. Fase 3 — Optimización de rutas

**Objetivo:** RF-16 a RF-22, RNF-02. Ref propuesta: sección 9 "Fase 3".

### BE

- [x] 3.BE.1 Migraciones para `route_revisions`, `route_stops`, `route_metrics`. Ref: sección 6.1. Depende de: 2.BE.8. Criterio: `alembic upgrade head` aplica UNIQUE `(route_id, revision)` y `(revision_id, sequence)`. **Hecho 2026-08-30**: Alembic [`c91d0e47f3b2`](../../backend/alembic/versions/c91d0e47f3b2_routing_route_revisions_stops_metrics.py). UNIQUE `uq_route_revisions_route_revision` `(route_id, revision)` y `uq_route_stops_revision_sequence` `(revision_id, sequence)`. FK `daily_routes.current_revision`. RLS ENABLE+FORCE en las tres tablas. Tests: [`test_routing_schema.py`](../../backend/tests/test_routing_schema.py) + [`test_routing_rls.py`](../../backend/tests/test_routing_rls.py).
- [x] 3.BE.2 Cálculo de matriz OSRM `/table` (NxN, incluyendo origen/retorno) con caché por hash de coordenadas redondeadas + perfil + versión de extracto. Ref: RF-16, sección 7.5, 11.5. Depende de: 0.BE.4, 3.BE.1. Criterio: test de integración obtiene matriz para 25 paradas y reutiliza caché en segunda llamada. **Hecho 2026-08-30**: [`matrix.py`](../../backend/app/modules/routing/matrix.py) caché Redis. 25 paradas (matriz 27×27); 2 `compute_matrix` → 1 `table()`. Clave sha256 `profile|dataset|coords` redondeadas a 5 decimales. Tests: [`test_routing_matrix.py`](../../backend/tests/test_routing_matrix.py).
- [x] 3.BE.3 🔀 **[Paralelizable]** Modelo OR-Tools TSP (sin ventanas) con límite de tiempo del solver inferior al SLA (p. ej. 10 s de 15 s). Ref: RF-16, RNF-02, ADR-10. Depende de: 3.BE.2. Criterio: benchmark de 25 paradas resuelve en < 15 s con `solver_status` reportado. **Hecho 2026-08-30**: `OrToolsTspOptimizer` ([`ortools_tsp.py`](../../backend/app/adapters/optimizer/ortools_tsp.py)). 25 paradas ~0.04 s; `time_limit` 10 s < SLA 15 s. `ortools>=9.15,<10`. Tests: [`test_optimizer_tsp.py`](../../backend/tests/test_optimizer_tsp.py). Informe p95 = **3.QA.1**.
- [x] 3.BE.4 🔀 **[Paralelizable]** Extensión a VRP/VRPTW: ventanas horarias, duración de visita, jornada, varios visitadores. Ref: RF-19, sección 7.5. Depende de: 3.BE.3. Criterio: caso con ventanas incompatibles devuelve diagnóstico de inviabilidad, no una solución silenciosamente incorrecta. **Hecho 2026-08-30**: VRPTW en el mismo optimizer. Ventanas incompatibles → `ROUTING_INFEASIBLE` + diagnósticos, `order` vacío (no tour silencioso). Tests: [`test_optimizer_vrptw.py`](../../backend/tests/test_optimizer_vrptw.py).
- [x] 3.BE.5 🔀 **[Paralelizable]** Función objetivo configurable: minimizar tiempo o minimizar coste (`distancia_km × coste_km + horas_viaje × coste_hora`). Ref: RF-17, sección 7.5. Depende de: 3.BE.3. Criterio: test unitario compara resultado con objetivo `time` vs `cost` sobre el mismo fixture. **Hecho 2026-08-30**: `time` vs `cost` sobre el mismo fixture produce órdenes distintas (`[0,1,2,3]` vs `[0,3,2,1]`). Tests: [`test_optimizer_vrptw.py`](../../backend/tests/test_optimizer_vrptw.py) (`test_time_and_cost_objectives_diverge_on_the_same_fixture`).
- [x] 3.BE.6 🔀 **[Paralelizable]** Cálculo de ruta "original" (orden importado/manual) sobre la misma matriz para comparación justa. Ref: RF-18, sección 7.5. Depende de: 3.BE.2. Criterio: `route_metrics` almacena variantes `original` y `optimized` con la misma matriz base. **Hecho 2026-08-30**: `original`+`optimized` comparten `matrix_hash`. Tests: [`test_routing_metrics.py`](../../backend/tests/test_routing_metrics.py).
- [x] 3.BE.7 Endpoint `POST /routes/{id}/optimize` (objetivo, origen/retorno, restricciones, versión, `Idempotency-Key`). Ref: RF-16, RF-17, RF-19, sección 8.5. Depende de: 3.BE.4, 3.BE.5, 3.BE.14. Criterio: llamada duplicada con la misma clave e igual payload devuelve la misma respuesta; payload distinto devuelve 409. **Hecho 2026-08-30**: `POST /api/v1/routes/{id}/optimize` **202** cola `optimization`; `Idempotency-Key` (replay mismo job; payload distinto → 409 `IDEMPOTENCY_KEY_REUSE`). Compose `worker-optimization`. pytest **299** incluyendo [`test_routing_optimize_e2e.py`](../../backend/tests/test_routing_optimize_e2e.py).
- [x] 3.BE.8 Endpoint `GET /routes/{id}/comparison` (métricas original/optimizada y ahorro). Ref: RF-18, sección 8.5. Depende de: 3.BE.6. Criterio: respuesta incluye distancia/tiempo/coste de ambas variantes. **Hecho 2026-08-30**: `GET /api/v1/routes/{id}/comparison` con `original`/`optimized`/`savings`. Métricas stale → **409 `METRICS_STALE`**. Tests: [`test_routing_comparison_e2e.py`](../../backend/tests/test_routing_comparison_e2e.py).
- [ ] 3.BE.9 🔀 **[Paralelizable]** Recalcular ruta al añadir/quitar/modificar paradas de una zona/día (nueva clave de idempotencia por cambio). Ref: RF-20, sección 11.1. Depende de: 3.BE.7. Criterio: modificar una parada invalida la clave anterior y permite nueva optimización.
- [x] 3.BE.10 Endpoint `PATCH /routes/{id}/stops/order` (reordenar manualmente con `If-Match`). Ref: RF-20, sección 8.5. Depende de: 3.BE.1. Criterio: reordenar manualmente marca métricas como pendientes de recalcular. **Hecho 2026-08-30**: `PATCH /api/v1/routes/{id}/stops/order` con `If-Match` sobre `daily_routes.version`; métricas `stale`. Tests: [`test_routing_order_e2e.py`](../../backend/tests/test_routing_order_e2e.py).
- [ ] 3.BE.11 🔀 **[Paralelizable]** Endpoint `POST /routes/{id}/publish` (snapshot inmutable de dirección, coordenadas, orden, métricas, geometría y versiones OSRM/OSM). Ref: RF-21, ADR-08, sección 7.6. Depende de: 3.BE.7. Criterio: publicar bloquea edición directa; un cambio posterior crea nueva revisión `draft`.
- [x] 3.BE.12 Manejo de inviabilidad: diagnóstico (ventanas incompatibles, jornada insuficiente, parada aislada) y opciones (ampliar ventana, dividir ruta, retirar parada, editar orden). Ref: RF-19, sección 7.5. Depende de: 3.BE.4. Criterio: test cubre al menos 2 escenarios de inviabilidad con mensaje explicativo. **Hecho 2026-08-30**: `GET /api/v1/routes/{id}` incluye `diagnostics` + `suggested_actions`. Dos códigos: `INCOMPATIBLE_WINDOWS`, `ISOLATED_STOP`. Tests: [`test_routing_optimize_e2e.py`](../../backend/tests/test_routing_optimize_e2e.py).
- [ ] 3.BE.13 Worker de exportación: PDF, PNG y enlace a app de navegación externa (`POST /routes/{id}/exports`). Ref: RF-22, sección 8.5. Depende de: 3.BE.11. Criterio: los 3 formatos se generan sin incluir datos innecesarios de paciente en el enlace externo.
- [x] 3.BE.14 Tabla `jobs` en Postgres + ledger de Idempotency-Key (reutilizar clave con payload distinto → 409). Ref: diseño 6.1, 8.1. Depende de: 0.BE.6. Criterio: test de payload distinto con la misma clave devuelve 409. **Hecho 2026-08-30**: Alembic [`d02e1f58a4c3`](../../backend/alembic/versions/d02e1f58a4c3_jobs_idempotency_ledger.py) (**head**). `begin_idempotent_job` → 409 `IDEMPOTENCY_KEY_REUSE`. Tests: [`test_jobs_ledger.py`](../../backend/tests/test_jobs_ledger.py). Cierra [status §3.3](../info/status.md#33-idempotency-key-sin-ledger-de-peticiónrespuesta). Residual: `POST /imports` sigue deduplicando por 1.BE.7, no por el ledger.

### FE

- [ ] 3.FE.1 🔀 **[Paralelizable]** Optimizador: selección de objetivo, origen/retorno, restricciones, progreso del job. Ref: RF-16, RF-17, RF-19, sección 3.2. Depende de: 3.BE.7. Criterio: E2E lanza optimización y muestra progreso hasta completar.
- [ ] 3.FE.2 Vista de diagnóstico e inviabilidad con acciones sugeridas. Ref: RF-19, sección 7.5. Depende de: 3.BE.12. Criterio: E2E de caso inviable muestra explicación y acciones disponibles.
- [ ] 3.FE.3 Comparación visual base/optimizada (mapa con orden numerado + tabla de métricas). Ref: RF-18, RF-21, sección 3.2. Depende de: 3.BE.8, 3.BE.11. Criterio: E2E muestra ahorro estimado entre ambas rutas.
- [ ] 3.FE.4 Exportación desde UI (PDF/PNG/enlace de navegación) con confirmación de riesgo si aplica. Ref: RF-22. Depende de: 3.BE.13. Criterio: E2E descarga PDF/PNG y copia enlace de navegación.

### QA

- [x] 3.QA.1 🔀 **[Paralelizable]** Benchmark de rendimiento: p95 de optimización con hasta 25 paradas < 15 s. Ref: RNF-02, sección 11.3. Depende de: 3.BE.3. Criterio: informe de benchmark documentado con hardware de referencia. **Hecho 2026-08-30**: [`scripts/qa/benchmark_tsp.py`](../../scripts/qa/benchmark_tsp.py) + [`tsp-benchmark.md`](../../scripts/qa/tsp-benchmark.md). p95 **0.0266 s** en i7-12700H (N=30, 25 paradas, semilla `20260830`).
- [ ] 3.QA.2 Suite E2E: recalcular tras modificar paradas, publicar, exportar. Ref: RF-20, RF-21, RF-22, sección 12. Depende de: 3.BE.9, 3.BE.11, 3.BE.13. Criterio: escenario completo en verde en CI.

## 8. Fase 4 — Histórico y colaboración

**Objetivo:** RF-23 a RF-30, RNF-11. Ref propuesta: sección 9 "Fase 4".

### BE — Histórico

- [ ] 4.BE.1 🔀 **[Paralelizable]** Consulta de histórico `GET /history/routes?from=&to=&zone=&assignee=&patient_ref=` sobre snapshots (no sobre el paciente actual). Ref: RF-23, RF-24, sección 7.6, 8.5. Depende de: 3.BE.11. Criterio: filtros combinados devuelven snapshots paginados correctos.
- [ ] 4.BE.2 🔀 **[Paralelizable]** Endpoint `PATCH /routes/{id}/stops/{stopId}` idempotente con `If-Match` para reportar ejecución (completada/no completada). Ref: RF-25, sección 7.6, 8.5. Depende de: 3.BE.11. Criterio: conflicto de concurrencia devuelve 409 con estado más reciente.
- [ ] 4.BE.3 🔀 **[Paralelizable]** Comparativa planificado vs. ejecutado usando `route_metrics.variant = actual`. Ref: RF-25, sección 6.1. Depende de: 4.BE.2. Criterio: endpoint/consulta devuelve desviación entre plan y ejecución real.
- [ ] 4.BE.4 Job de retención/purga configurable (por defecto 12 meses) con anonimización y acta técnica. Ref: RF-26, RNF-06, sección 7.6, 9.2. Depende de: 4.BE.1, 0.DATA.4. Criterio: ejecutar el job sobre datos de fixture antiguos los anonimiza/purga y genera acta con conteos.

### BE — Compartición y auditoría

- [ ] 4.BE.5 Migración para `share_grants` con CHECK "sujeto XOR token". Ref: sección 6.1. Depende de: 3.BE.1. Criterio: intento de crear grant con sujeto y token a la vez falla por constraint.
- [ ] 4.BE.6 Endpoint `POST /routes/{id}/shares` (compartición interna con permiso `view`/`edit`). Ref: RF-27, sección 7.7, 8.6. Depende de: 4.BE.5, 0.BE.5. Criterio: usuario con `view` no puede modificar la ruta; usuario con `edit` sí, si el rol lo permite.
- [ ] 4.BE.7 Endpoint `POST /routes/{id}/shares` para token externo (256+ bits, solo hash en BD, expiración obligatoria) y `POST /public-shares/exchange`. Ref: RF-28, sección 7.7, 8.6. Depende de: 4.BE.5. Criterio: token vencido o revocado devuelve 401/410; vista externa oculta campos sensibles por defecto.
- [ ] 4.BE.8 🔀 **[Paralelizable]** Endpoint `DELETE /shares/{id}` (revocación) con auditoría. Ref: RF-27, RF-28, sección 7.7. Depende de: 4.BE.6, 4.BE.7. Criterio: revocar invalida acceso inmediato (verificado en test de integración).
- [ ] 4.BE.9 Outbox transaccional de notificaciones al compartir/reasignar rutas. Ref: RF-29, sección 7.4, 11.1. Depende de: 2.BE.13, 4.BE.6. Criterio: compartir/reasignar genera notificación consumida de forma idempotente (`event_id`). **Nota 2026-08-30:** 2.BE.13 `[x]` adelantó la tabla `outbox_events` (Alembic `e4c8a2b91d07`, evento `plan.published`, `processed_at` nulo). Esta tarea es el **consumidor** idempotente + eventos de share/reasignar; no duplicar la tabla.
- [ ] 4.BE.10 Endpoints `GET /notifications`, `PATCH /notifications/{id}`. Ref: RF-29, sección 8.6. Depende de: 4.BE.9. Criterio: E2E marca notificación como leída.
- [ ] 4.BE.11 Tabla `audit_events` append-only con encadenado de hashes (`prev_hash`/`event_hash`). Ref: RF-30, RNF-11, sección 6.1. Depende de: 0.DATA.2. Criterio: intento de modificar un evento de auditoría rompe la cadena de hashes en test.
- [ ] 4.BE.12 Emisión de eventos de auditoría en ver/editar/borrar/exportar/optimizar/publicar/acceso externo/administración. Ref: RF-30, RNF-11, sección 9.1. Depende de: 4.BE.11 y las tareas de cada acción correspondiente (3.BE.11, 4.BE.6, 4.BE.7, 4.BE.8). Criterio: cada acción listada genera exactamente un evento auditable con actor y fecha/hora.
- [ ] 4.BE.13 Endpoint `GET /audit-events?resource_type=&resource_id=&from=&to=`. Ref: RF-30, sección 8.6. Depende de: 4.BE.11. Criterio: consulta filtrada devuelve eventos minimizados y respeta autorización por rol.

### FE

- [ ] 4.FE.1 Vista de histórico: búsqueda por fecha/zona/usuario/referencia, comparación plan/ejecución, acceso a snapshots. Ref: RF-24, RF-25, sección 3.2. Depende de: 4.BE.1, 4.BE.3. Criterio: E2E filtra histórico y muestra comparación planificado vs. ejecutado.
- [ ] 4.FE.2 🔀 **[Paralelizable]** Panel de compartición: usuarios, permiso, caducidad, revocación, vista previa minimizada, confirmación de riesgo externo. Ref: RF-27, RF-28, sección 3.2. Depende de: 4.BE.6, 4.BE.7. Criterio: E2E crea, revisa vista previa y revoca una compartición externa.
- [ ] 4.FE.3 Notificaciones in-app de asignación/compartición. Ref: RF-29. Depende de: 4.BE.10. Criterio: E2E recibe notificación al ser asignado/compartido.
- [ ] 4.FE.4 Vista de consulta de auditoría en administración. Ref: RF-30, sección 3.2. Depende de: 4.BE.13. Criterio: E2E de administrador consulta eventos de una ruta concreta.
- [ ] 4.FE.5 🔀 **[Paralelizable]** Ruta de campo: estado completada/no completada, tolerante a reconexión, sin almacenar teselas públicas offline. Ref: RF-25, sección 3.2, 10.2. Depende de: 4.BE.2. Criterio: E2E marca parada completada tras reconexión simulada sin duplicar el reporte.

### QA

- [ ] 4.QA.1 Suite E2E: compartir con permiso `view`/`edit`, revocar, exportar histórico, verificar auditoría inmutable. Ref: RF-27 a RF-30, sección 12. Depende de: 4.BE.12, 4.FE.2. Criterio: escenario completo en verde en CI con los 4 roles.
- [ ] 4.QA.2 Prueba de purga/retención con verificación de acta técnica y comprobación en réplicas/backups. Ref: RF-26, sección 11.4. Depende de: 4.BE.4. Criterio: ejecución documentada del job de purga sobre entorno de pruebas.

## 9. Fase 5 — Pruebas, seguridad y despliegue

**Objetivo:** RNF-03 a RNF-06, RNF-10, hardening y puesta en producción. Ref propuesta: sección 9 "Fase 5".

### SEC

- [ ] 5.SEC.1 🔀 **[Paralelizable]** Pentest/DAST sobre autorización objeto a objeto, CSRF/XSS/CSP, subida maliciosa de ficheros, tokens y rate limits. Ref: RNF-05, RNF-06, sección 12 (seguridad). Depende de: fases 1-4 completas. Criterio: informe de pentest sin hallazgos críticos abiertos.
- [ ] 5.SEC.2 Verificación de RBAC + RLS de extremo a extremo (matriz de permisos por rol y por ACL de ruta). Ref: RNF-06, sección 9.1. Depende de: 0.BE.5, 0.DATA.3, 4.BE.6. Criterio: matriz de pruebas cubre las combinaciones rol × acción × recurso definidas en el diseño.
- [ ] 5.SEC.3 Revisión de redacción de logs (sin direcciones, tokens, nombres ni cuerpos de fichero). Ref: sección 9.1, 11.3. Depende de: 0.BE.7. Criterio: auditoría de logs de un flujo completo no contiene datos personales.
- [ ] 5.SEC.4 Validar cifrado en tránsito (TLS 1.2+, HSTS) y en reposo (volúmenes, backups, campos sensibles). Ref: RNF-05. Depende de: 0.DATA.4, 4.1 (despliegue). Criterio: escaneo TLS y prueba de descifrado autorizado documentados.
- [ ] 5.SEC.5 Implementar MFA obligatorio para `admin`/`planner` y Argon2id para contraseñas locales. Ref: sección 9.1. Depende de: 0.BE.5. Criterio: intento de login sin MFA para rol obligatorio es rechazado.
- [ ] 5.SEC.6 Hardening de adaptador de proveedor de pago (Google/Mapbox) como apagado por defecto, con allowlist y aprobación. Ref: RNF-10, sección 10.3. Depende de: 0.BE.2. Criterio: activar el adaptador de pago requiere configuración explícita por organización y deja evento de auditoría.
- [ ] 5.SEC.7 Integrar ClamAV (servicio Docker + escaneo en `POST /imports` antes de persistir). Ref: RF-04, RNF-05, deuda de 1.BE.1. Depende de: 1.BE.1. Criterio: eicar/firma maliciosa → 415/422; fichero limpio pasa.

### DATA / Infra

- [ ] 5.DATA.1 Configurar backup PostgreSQL (completo diario + WAL/PITR) cifrado y fuera del host. Ref: sección 11.4, RNF-04. Depende de: 0.DATA.1. Criterio: prueba de restauración documentada cumple RPO/RTO objetivo.
- [ ] 5.DATA.2 🔀 **[Paralelizable]** Prueba automática de restauración mensual en entorno aislado. Ref: sección 11.4. Depende de: 5.DATA.1. Criterio: ejecución registrada con duración, integridad y conteos verificados.
- [ ] 5.DATA.3 Desplegar 2 réplicas de API con health checks y reinicio automático para SLO 99% en horario laboral. Ref: RNF-04, sección 4.1. Depende de: 0.CI.2. Criterio: prueba de caída de una réplica no interrumpe el servicio.
- [ ] 5.DATA.4 Pruebas de carga multi-organización (≥10 cargas concurrentes de 500 filas + optimizaciones paralelas). Ref: RNF-03, sección 11.5. Depende de: 1.BE.2, 3.BE.7. Criterio: informe de carga sin degradación relevante ni errores 5xx.
- [ ] 5.DATA.5 🔀 **[Paralelizable]** Runbooks de incidentes: pérdida de DB, corrupción, caída de proveedor OSM, fuga de token, clave comprometida, cola atascada, rollback de extracto OSM. Ref: sección 11.4. Depende de: 5.DATA.1. Criterio: 7 runbooks documentados y validados con un simulacro cada uno.

### QA

- [ ] 5.QA.1 Suite de pruebas de seguridad automatizadas (SAST + dependency/container scan) integrada en CI. Ref: RNF-05, RNF-06. Depende de: 0.CI.1. Criterio: pipeline bloquea merge ante vulnerabilidad crítica/alta.
- [ ] 5.QA.2 🔀 **[Paralelizable]** Validación final de criterios de aceptación del documento de requisitos (geocodificación ≥95%, ahorro 15-20% de referencia, disponibilidad histórico inmediata, permisos view/edit). Ref: sección 9 (criterios de aceptación) del documento de requisitos. Depende de: fases 1-4 completas. Criterio: informe de aceptación firmado por el equipo de producto.
- [ ] 5.QA.3 Formación a usuarios y periodo de acompañamiento en el despliegue piloto. Ref: RNF-07, sección 13 (propuesta). Depende de: 5.QA.2. Criterio: sesión de formación realizada con al menos un equipo piloto y feedback recogido.

### Despliegue

- [ ] 5.DEPLOY.1 Provisionar infraestructura de producción (redes, secretos, PostgreSQL/PostGIS, almacenamiento, observabilidad, backups) según sección 4 del diseño. Depende de: 0.DATA.1, 5.DATA.1. Criterio: checklist de infraestructura de producción completado.
- [ ] 5.DEPLOY.2 Desplegar API/workers/frontend tras TLS en staging con dataset ficticio únicamente. Ref: sección 13. Depende de: 5.DEPLOY.1. Criterio: entorno de staging accesible solo con datos ficticios cargados.
- [ ] 5.DEPLOY.3 Piloto con un equipo real, feature flags para zonificación/optimización/share externo y monitorización reforzada. Ref: sección 13. Depende de: 5.QA.2, 5.QA.3. Criterio: piloto ejecutado con flags activables/desactivables de forma independiente.
- [ ] 5.DEPLOY.4 Activación progresiva de equipos y verificación de rollback (deshabilitar flags, volver a imagen/API compatible). Ref: sección 13. Depende de: 5.DEPLOY.3. Criterio: prueba de rollback documentada sin pérdida de snapshots publicados.

## 10. Tareas transversales

No pertenecen a una única fase; se ejecutan en paralelo desde que su dependencia esté disponible.

### Observabilidad

- [ ] T.OBS.1 Métricas de negocio y técnicas (latencia/errores HTTP, jobs por estado/cola, filas/min, match/ambigüedad, latencia Nominatim/OSRM, tiempo/estado OR-Tools, ahorro, accesos externos). Ref: sección 11.3. Depende de: 0.BE.6. Criterio: dashboard muestra las métricas listadas con datos de fixture.
- [ ] T.OBS.2 Trazas OpenTelemetry desde API a job y dependencias, con atributos filtrados (sin datos sensibles). Ref: sección 11.3. Depende de: 0.BE.1. Criterio: traza de un flujo de importación visible de extremo a extremo.
- [ ] T.OBS.3 Alertas basadas en error budget para SLO internos (geocodificación < 5 min, optimización p95 < 15 s, disponibilidad 99%). Ref: RNF-01, RNF-02, RNF-04, sección 11.3. Depende de: T.OBS.1. Criterio: alerta se dispara en simulación de incumplimiento de SLO.

### CI/CD

- [ ] T.CI.1 🔀 **[Paralelizable]** Pipeline de despliegue continuo a staging tras merge a rama principal, con migraciones automáticas y smoke tests. Ref: sección 13. Depende de: 0.CI.1. Criterio: merge de ejemplo despliega a staging y ejecuta smoke test en verde.
- [ ] T.CI.2 🔀 **[Paralelizable]** Gate de calidad: cobertura mínima de pruebas unitarias/integración y bloqueo de merge si baja del umbral acordado. Ref: DoD general. Depende de: 0.CI.1. Criterio: PR con cobertura por debajo del umbral es bloqueado automáticamente.

### Documentación

- [ ] T.DOC.1 Especificación OpenAPI mantenida y publicada (contrato de todos los endpoints del diseño, sección 8). Depende de: 1.BE.1. Criterio: `openapi.json` generado valida contra los ejemplos de la sección 8 del diseño.
- [ ] T.DOC.2 Guía de despliegue autoalojado (Nominatim/OSRM/PostgreSQL/PostGIS) con procedimiento de actualización de extracto OSM. Ref: sección 4.1, 13. Depende de: 0.DATA.5. Criterio: guía permite a una persona nueva reproducir el entorno en un host limpio.
- [ ] T.DOC.3 Manual de usuario por rol (`admin`, `planner`, `field`, `supervisor`). Ref: RNF-07. Depende de: fases 1-4 (funcionalidades por rol). Criterio: manual revisado por al menos un usuario de cada rol.

### Cumplimiento RGPD

- [ ] T.RGPD.1 🔀 **[Paralelizable]** Registro de Actividades de Tratamiento (RAT) y Evaluación de Impacto (EIPD) para datos de salud/localización, con asesoría jurídica. Ref: RNF-06, sección 9.2, decisión pendiente 13. Depende de: —. Criterio: documentos RAT/EIPD aprobados por el responsable de tratamiento antes de datos reales.
- [ ] T.RGPD.2 Procedimiento de ejercicio de derechos (acceso, rectificación, supresión) y protocolo de notificación de brechas. Ref: RNF-06, sección 9.2. Depende de: T.RGPD.1. Criterio: procedimiento documentado y probado con un caso simulado.
- [ ] T.RGPD.3 Política de retención por finalidad validada jurídicamente (por defecto 12 meses) y su aplicación técnica en el job de purga. Ref: RF-26, RNF-06, sección 9.2. Depende de: T.RGPD.1, 4.BE.4. Criterio: política firmada coincide con la configuración activa del job de purga.
- [ ] T.RGPD.4 Revisión de contratos de encargo de tratamiento con proveedores externos (si se activa un adaptador de pago). Ref: sección 9.2, 10.3. Depende de: T.RGPD.1, 5.SEC.6. Criterio: contrato/DPA firmado antes de habilitar cualquier proveedor de pago en producción.

## 11. Matriz de cobertura RF/RNF → tareas

### 11.1 Requisitos funcionales

| Requisito | Tarea(s) que lo cubren |
|---|---|
| RF-01 | 1.BE.1, 1.FE.1 |
| RF-02 | 1.BE.2, 1.BE.3, 1.BE.4, 1.FE.2 |
| RF-03 | 1.BE.5, 1.BE.12, 1.FE.3 |
| RF-04 | 1.BE.1, 1.BE.2, 5.SEC.7 |
| RF-05 | 1.BE.8, 1.BE.9, 1.BE.10, 1.BE.11, 1.DATA.3 |
| RF-06 | 1.FE.4 |
| RF-07 | 1.FE.5 |
| RF-08 | 1.FE.6 |
| RF-09 | 2.BE.3, 2.BE.5 |
| RF-10 | 2.BE.6, 2.FE.1 |
| RF-11 | 2.BE.3 |
| RF-12 | 2.BE.2, 2.BE.4, 2.FE.3 |
| RF-13 | 2.BE.9, 2.BE.10, 2.BE.11, 2.FE.2 |
| RF-14 | 2.BE.12, 2.FE.2 |
| RF-15 | 2.BE.13, 2.BE.14 |
| RF-16 | 3.BE.2, 3.BE.3, 3.BE.7 |
| RF-17 | 3.BE.5 |
| RF-18 | 3.BE.6, 3.BE.8, 3.FE.3 |
| RF-19 | 3.BE.4, 3.BE.12, 3.FE.2 |
| RF-20 | 3.BE.9, 3.BE.10 |
| RF-21 | 3.BE.11, 3.FE.3 |
| RF-22 | 3.BE.13, 3.FE.4 |
| RF-23 | 3.BE.11, 4.BE.1 |
| RF-24 | 4.BE.1, 4.FE.1 |
| RF-25 | 4.BE.2, 4.BE.3, 4.FE.1, 4.FE.5 |
| RF-26 | 4.BE.4, 4.QA.2, T.RGPD.3 |
| RF-27 | 4.BE.6, 4.BE.8, 4.FE.2 |
| RF-28 | 4.BE.7, 4.BE.8, 4.FE.2 |
| RF-29 | 4.BE.9, 4.BE.10, 4.FE.3 |
| RF-30 | 4.BE.11, 4.BE.12, 4.BE.13, 4.FE.4 |

### 11.2 Requisitos no funcionales

| Requisito | Tarea(s) que lo cubren |
|---|---|
| RNF-01 | 1.BE.9, 1.BE.14 |
| RNF-02 | 3.BE.3, 3.QA.1 |
| RNF-03 | 5.DATA.4 |
| RNF-04 | 5.DATA.3, T.OBS.3 |
| RNF-05 | 5.SEC.1, 5.SEC.4, 1.DATA.2, 5.SEC.7 |
| RNF-06 | 0.DATA.3, 5.SEC.2, T.RGPD.1, T.RGPD.2, T.RGPD.3 |
| RNF-07 | 1.FE.8, T.DOC.3 |
| RNF-08 | 1.FE.7 |
| RNF-09 | 1.QA.2 |
| RNF-10 | 0.BE.2, 5.SEC.6 |
| RNF-11 | 4.BE.11, 4.BE.12 |

**Resultado de la validación de cobertura:** todos los requisitos RF-01 a RF-30 y RNF-01 a RNF-11 quedan cubiertos por al menos una tarea. No se detectaron huecos.

## 12. Tareas paralelizables por fase

Tareas marcadas con 🔀 **[Paralelizable]** en las secciones 4 a 10: no declaran `Depende de:` (pueden arrancar de inmediato dentro de su fase) o comparten exactamente el mismo conjunto de dependencias que otra(s) tarea(s), por lo que pueden ejecutarse a la vez una vez cumplida esa dependencia común. Agrupadas en oleadas (wave) para planificar sprints con varias personas trabajando en paralelo: wave 1 = sin dependencias, se puede empezar ya; wave N = depende solo de tareas resueltas en oleadas anteriores.

### Fase 0 — Preparación

- **Wave 1** (sin dependencias): 0.DATA.1, 0.DATA.4, 0.BE.1, 0.CI.1, 0.QA.1
- **Wave 2** (dependen de tareas de wave 1): 0.DATA.2, 0.DATA.5 (dependen de 0.DATA.1); 0.BE.2, 0.BE.7 (dependen de 0.BE.1)
- **Wave 3** (dependen de wave 2): 0.BE.3, 0.BE.4 (dependen de 0.BE.2 y 0.DATA.5)

### Fase 1 — MVP: importación, geocodificación y mapa

- **Wave 1** (dependen solo de tareas base de Fase 0): 1.BE.7, 1.FE.1 (dependen de 1.BE.1)
- **Wave 2**: 1.BE.3, 1.BE.4, 1.QA.2 (dependen de 1.BE.2)
- **Wave 3**: 1.BE.9, 1.BE.10 (dependen de 1.BE.8)
- **Wave 4**: 1.BE.11, 1.BE.12, 1.BE.13 (dependen de 1.BE.10)
- **Wave 3** (rama FE, en paralelo a las anteriores): 1.FE.7, 1.FE.8 (dependen de 1.FE.1 y 1.FE.4)

### Fase 2 — Zonificación y planificación

- **Wave 1** (cerrada): 2.BE.5 `[x]`, 2.QA.2 `[x]` (dependen de 2.BE.3 `[x]`)
- **Wave 2** (cerrada): 2.BE.4 `[x]` y 2.QA.2 `[x]` (tras 2.BE.3); 2.BE.6 `[x]` (tras 2.BE.5); 2.BE.11 `[x]` (tras 2.BE.10)
- **Wave 3** (cerrada): 2.BE.7 `[x]` (tras 2.BE.4); 2.FE.1 `[x]` (tras 2.BE.6); 2.BE.12 `[x]` (tras 2.BE.11)
- **Wave 4** (cerrada 2026-08-30): 2.FE.2 `[x]` (tras 2.BE.12); 2.BE.13 `[x]` (tras 2.BE.12); 2.FE.3 `[x]` (tras 2.FE.1); 2.BE.14 `[x]`; 2.QA.1 `[x]` (cierre Fase 2)

### Fase 3 — Optimización de rutas

- **Wave 1** (cerrada): 3.BE.3 `[x]`, 3.BE.6 `[x]` (dependen de 3.BE.2 `[x]`)
- **Wave 2** (cerrada): 3.BE.4 `[x]`, 3.BE.5 `[x]`, 3.QA.1 `[x]` (dependen de 3.BE.3 `[x]`)
- **Wave 3** (desbloqueada): 3.BE.9, 3.BE.11, 3.FE.1 (dependen de 3.BE.7 `[x]`). 3.FE.2 desbloqueada por 3.BE.12 `[x]`. 3.BE.13 / 3.FE.3 / 3.QA.2 siguen esperando 3.BE.11.

### Fase 4 — Histórico y colaboración

- **Wave 1**: 4.BE.1, 4.BE.2 (dependen de 3.BE.11)
- **Wave 2**: 4.BE.3, 4.FE.5 (dependen de 4.BE.2); 4.BE.8, 4.FE.2 (dependen de 4.BE.6 y 4.BE.7)

### Fase 5 — Pruebas, seguridad y despliegue

- **Wave 1**: 5.DATA.2, 5.DATA.5 (dependen de 5.DATA.1)
- **Wave 2** (requiere fases 1-4 completas): 5.SEC.1, 5.QA.2

### Transversal

- **Wave 1**: T.RGPD.1 (sin dependencias); T.CI.1, T.CI.2 (dependen de 0.CI.1, tarea base de Fase 0)

## 13. Referencias

- [Documento de requisitos](../requisitos/requisitos-app-rutas-pacientes.md)
- [Propuesta técnica y funcional](../propuesta/propuesta-app-rutas-pacientes.md)
- [Diseño técnico](../diseno/diseno-app-rutas-pacientes.md)
- [Dataset ficticio de Bizkaia](../requisitos/direcciones-ejemplo-bizkaia.csv)
