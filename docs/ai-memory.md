# Memoria de agente — Sofia / MapyCar

Memoria operativa para implementaciones futuras. **No** sustituye:

| Documento | Rol |
|---|---|
| [`diseno/diseno-app-rutas-pacientes.md`](diseno/diseno-app-rutas-pacientes.md) | Contrato técnico (ADRs, API, modelo) |
| [`tareas/tareas-app-rutas-pacientes.md`](tareas/tareas-app-rutas-pacientes.md) | WBS: fuente de verdad tarea a tarea |
| [`info/status.md`](info/status.md) | Resumen ejecutivo, deuda y siguiente corte |
| [`requisitos/requisitos-app-rutas-pacientes.md`](requisitos/requisitos-app-rutas-pacientes.md) | RF/RNF |
| [`propuesta/propuesta-app-rutas-pacientes.md`](propuesta/propuesta-app-rutas-pacientes.md) | Alcance y fases |

Actualizar este fichero cuando cierre un corte de producto, un ADR de implementación o una convención que el código ya aplica y el diseño aún no reescribe.

| Campo | Valor |
|---|---|
| Producto | Sofia (código/env `SOFIA_*`); repo MapyCar |
| Última actualización | 2026-09-18 |
| Fase | 4 iniciada **11/20**. Fase 3 **20/20**. Fase 2 19/19. Fase 1 código 27/28 (solo **1.FE.8** humana) |
| Siguiente corte | **4.BE.10** GET/PATCH notificaciones. No arrancar Fase 5 como camino principal |

---

## 1. Architecture decisions

### 1.1 ADRs de diseño (vigentes)

| ID | Decisión |
|---|---|
| ADR-01 | Monolito modular FastAPI/Python + workers por cola. No microservicios. |
| ADR-02 | React + TypeScript + Vite + Leaflet/OSM. Un cliente escritorio/campo. |
| ADR-03 | REST JSON `/api/v1` + OpenAPI. No GraphQL. |
| ADR-04 | PostgreSQL 17 + PostGIS = sistema de registro. |
| ADR-05 | Redis = transporte de cola; el estado durable de jobs vive en Postgres. |
| ADR-06 | Adaptadores `Geocoder`, `Router`, `Optimizer`, `TileProvider`, `ObjectStore`. Nunca invocar Nominatim/OSRM/S3 desde un router HTTP. |
| ADR-07 | Nominatim + OSRM autoalojados, extracto Euskadi. APIs públicas solo dev manual de bajo volumen. |
| ADR-08 | Ruta publicada = snapshot inmutable. Un cambio posterior abre revisión `draft`. |
| ADR-09 | Seudónimo operativo (`display_ref` / `external_ref`). Dirección cifrada a nivel de campo (AES-256-GCM). No es anonimización. Sin dato clínico. |
| ADR-10 | Optimización en dos etapas: matriz OSRM `/table` + OR-Tools TSP/VRPTW. Inviable → diagnóstico, no tour silencioso. |
| ADR-11 | Todo en contenedores (Compose). Kubernetes no es requisito inicial. |

### 1.2 Deltas ya en código (diseño aún no reescrito)

Anotar aquí; no reabrir como tarea WBS. Detalle en status §3.11–3.15.

- Publicar plan y publicar ruta responden **200** (una transacción). Diseño §8.4 sugería 202 para planes; §8.1 reserva 202 a trabajos **largos**. Un 202 dejaría un worker que puede fallar después de marcar `published`.
- Tabla `outbox_events` existe (Alembic `e4c8a2b91d07`, evento `plan.published`). Consumidor **4.BE.9 `[x]`** (Alembic `c4f1d82e90a3`, tabla `notifications`, UNIQUE `event_id`+`recipient_id`). No duplicar la tabla. GET/PATCH = 4.BE.10.
- Tabla `zone_proposals` existe; no está en diseño §6.1. Propuesta ≠ zona persistida (`POST /zones` / accept).
- `monthly_plans.status` usa `validating`, no `validated` (`validated` es de `ImportBatch`).
- `monthly_plans.result_json` / `conflicts_json` / `job_id` guardan el solver; no reutilizar `constraints_json` para eso.
- `GET /patients` existe para mapa/bandeja; no está en diseño §8.3.
- Geometría OSRM de ruta publicada: `route_revisions.constraints_json.snapshot` (GeoJSON LineString). No hay columna dedicada.
- Geocodificación: Nominatim primario + overlay local `data/housenumber_overlay.csv` (1.DATA.3). No volcar Eustat a OSM.org. No insertar coords del ground truth en el matcher.
- Cohesión OSRM **sí** en el worker de propuestas: clustering → `apply_cohesion` → fallback municipio/CP si `Router.table` falla.

### 1.3 Módulos backend (límites)

`identity` · `imports` · `geocoding` · `zoning` · `planning` · `routing` · `history` · `jobs` · `sharing` · `notifications` (outbox + in-app) · (pendiente: `audit`).

- `routing` no decide permisos ni retención.
- `history` lee snapshots publicados; no muta revisiones. `patient_ref` filtra `snapshot.order.external_ref`, no el `Patient` vivo.
- `planning` no calcula la matriz viaria.
- `jobs` no implementa dominio; ledger + cola.
- `notifications` no es fuente de estado de negocio.
- El frontend oculta acciones por UX; **cada petición se autoriza de nuevo en backend**.

### 1.4 Flujo de producto (hasta donde hay código)

1. Importar CSV/XLSX/XLS → validar (worker `imports`) → corregir → commit pacientes.
2. Geocodificar (worker `geocoding`) → bandeja de ambiguos/manual.
3. Proponer zonas (worker `zoning`) → override → persistir zonas.
4. Generar plan (worker `planning`) → mover visitas (dry-run + confirm) → **publicar plan 200** → `daily_routes` draft.
5. Optimizar ruta 202 (worker `optimization`) → comparar → reordenar / sustituir paradas → **publicar ruta 200** (snapshot).
6. Exportar PDF/PNG/enlace (ruta publicada). Histórico `GET /history/routes` sobre snapshots.
7. Ejecución de paradas → histórico/campo. Share interno/externo/revocación + UI `/compartir` (4.BE.6–8, 4.FE.2). Outbox consumido (4.BE.9). GET/PATCH notificaciones y auditoría: resto de Fase 4. No atajar.

---

## 2. Coding conventions

### 2.1 Lenguaje y estilo

- Backend: Python 3.12 en CI (`requires-python >=3.12`). Ruff `line-length = 100`, `target-version = py312`. Ignorar B008 (Depends en defaults FastAPI).
- Frontend: TypeScript, Vite, oxlint, Vitest + Testing Library. **No Playwright** hasta que una tarea lo pida.
- Comentarios: cortos, factuales, en español; solo restricciones no obvias. Nada de narrativa de implementación.
- Errores de API al usuario: español. Códigos estables `SNAKE_CASE`.
- Env: prefijo `SOFIA_` (`pydantic-settings`). No secretos en el repo; Compose de dev usa valores no productivos.

### 2.2 API HTTP

- Prefijo `/api/v1`. IDs UUID (v7 en PK). Fechas ISO 8601.
- `organization_id` va **explícito** (query/path/form) **antes** de leer filas: RLS necesita `app.current_organization_id`.
- Auth actual: Bearer de sesión (login/password). OIDC/MFA = 5.SEC.5, no improvisar.
- `Idempotency-Key` obligatorio en importación, commit, optimize, publish de ruta, (futuro: export/share). Misma clave + mismo hash → replay. Misma clave + payload distinto → **409 `IDEMPOTENCY_KEY_REUSE`**. Ledger: `begin_idempotent_job` sobre `jobs` UNIQUE `(organization_id, type, idempotency_key)`.
- `If-Match` / `ETag` en escrituras de zona, plan, ruta, paradas. Token = columna `version` del agregado: `daily_routes.version` para planificación (optimize/reorder/replace/publish); **`route_stops.version`** para `PATCH …/stops/{stopId}` (ejecución). `route_revisions` **no** tiene `version`.
- **202** solo trabajos largos (`job_id`, cola Redis). Publish de plan/ruta = **200**.
- Errores: `DomainError(status, code, detail, errors=None)` → body `type/title/status/code/detail/instance/request_id/errors`. Base `https://sofia.example/errors`. El 409 de ejecución mete el estado más reciente en `errors[0]`.
- Códigos: 400 estado/sintaxis, 401, 403 rol/org, 404 no visible, 409 versión/idempotencia/conflicto, 413, 415, 422 dominio, 429, 503 dependencia, 504. **404 puede sustituir 403** para no enumerar (assignee otra org → `ASSIGNEE_NOT_FOUND` 404).
- `X-Request-ID` de correlación; nunca IDs de paciente.

### 2.3 Persistencia y servicios

- SQLAlchemy 2 mapped columns; sesiones síncronas. `get_db` no hace commit automático: el servicio hace `commit` al éxito.
- Escrituras concurrentes: `SELECT … FOR UPDATE` en el agregado (plan/ruta/revisión).
- JSONB: asignar dict nuevo (+ `flag_modified` si se muta anidado).
- Cifrado de campo: `FieldCipher` / `ObjectCipher`, envelope `key_id:nonce+ciphertext` (campo en Base64). Claves: env en tests/dev; Vault en 0.DATA.4. Rotar clave activa no debe romper ciphertexts viejos.
- ObjectStore: S3/MinIO con cifrado at-rest (`S3ObjectStore`). Sin `SOFIA_S3_ENDPOINT_URL` → `InMemoryObjectStore` (solo tests/API local). Workers **deben** copiar el mismo env S3 o no ven uploads.
- Jobs: Redis = cola; un proceso `python -m app.jobs.worker <cola>` por cola (`imports`, `geocoding`, `zoning`, `planning`, `optimization`, `exports`, `notifications`). No varias colas en un proceso.
- Fake adapters en e2e HTTP (`FakeRouter`, `FakeGeocoder`, `InMemoryObjectStore`). No pegar a Nominatim/OSRM reales en pytest.

### 2.4 Frontend

- Tipos en `frontend/src/api/types.ts` alineados con schemas Pydantic.
- Rutas UI existentes: login, import wizard/progress, geocoding tray, mapa operativo, editor de zonas, calendario de plan, **optimizador** (`/optimizacion`), **histórico** (`/historico`), **campo** (`/campo`), **compartir** (`/compartir`: 4.FE.2, interno/externo, preview minimizada, revocar).
- Leaflet: no prefetch masivo de teselas OSM; no offline de teselas públicas.
- Distinción urbana/rural: `ZoneKindBadge` (SVG + label + clase), no solo color.

### 2.5 Tests

- Backend e2e = pytest + TestClient + testcontainers PostGIS 17 (`postgis/postgis:17-3.4`). Rol `sofia_app_role` NOSUPERUSER NOBYPASSRLS (el superusuario ignora RLS).
- Sin Docker/Podman: tests de BD se **omiten**. Alternativa: `SOFIA_TEST_DATABASE_URL` a una PostGIS **dedicada** (CREATE EXTENSION/ROLE).
- Redis en tests: `fakeredis`. S3: `moto`. Vault real: testcontainers; se omite sin runtime.
- Frontend: Vitest. Criterios WBS “E2E” de FE se cierran con Vitest salvo que la tarea pida Playwright.
- Dataset ficticio Bizkaia; CSV `;`. No pacientes reales en CI.
- Semillas fijas en benchmarks (TSP `20260830`).

---

## 3. Team preferences

Cómo se trabaja en este repo (WBS + status + sesiones):

1. **El corte es el WBS**, no “mejoras”. Siguiente código: **4.BE.10**. **1.FE.8** es humana (protocolo ≠ informe); no cerrarla en código. Fase 3 está cerrada (20/20). Fase 4 11/20 (4.BE.1–3, 4.BE.5–9, 4.FE.1–2, 4.FE.5).
2. **No arrancar Fase 5 como camino principal.** ClamAV = **5.SEC.7**, no 1.BE.1. DoD de PR (segundo revisor) **no** es una fila WBS; `[x]` acredita código+tests, **no** production-ready.
3. Seguir **diseño + propuesta**. Si el diseño y una implementación previa divergen (200 vs 202), copiar el criterio ya aplicado y anotar en status; no reabrir el debate.
4. Cambios acotados a la tarea. No reescribir docs de diseño enteros; sí marcar el checkbox WBS y refrescar status §2/§6 al cerrar.
5. Verificar UI en navegador si se toca FE. Backend: tests del módulo + ruff.
6. No inventar portales OSM. Overlay local / GT oficial (Eustat/Cartociudad). Las 4 filas enmendadas del GT **siguen en el denominador**.
7. Logs/auditoría/export: sin direcciones en claro, sin tokens, sin nombres, sin cuerpos de fichero.
8. Proveedor de pago (Google/Mapbox) **apagado** hasta DPA + aprobación. Nunca fallback automático que envíe PII a un tercero.
9. Idioma de producto: es-ES. Zona horaria de visita: `Europe/Madrid`. Instante en UTC.
10. Volumen: 200 pacientes/mes nominal, 500 filas/fichero máx., **25 paradas** máx. por ruta (matriz 27×27 con origen/retorno).

Roles: `admin`, `planner`, `field`, `supervisor`. Edición de planes/rutas/zonas/import: **admin o planner**. Field no reordena ni publica.

---

## 4. Database patterns

### 4.1 Invariantes

- Toda tabla multi-tenant: `organization_id UUID NOT NULL`. RLS ENABLE+FORCE. Contexto `SET app.current_organization_id`.
- PK UUIDv7 (`app.core.ids.uuid7`). UNIQUE `(id, organization_id)` donde hay FK compuesta tenant-safe.
- FK de negocio: pares `(id, organization_id)` para no cruzar tenants.
- Optimistic lock: entero `version`, default 1; If-Match.
- Geometría: `geography(Point,4326)` en direcciones/paradas; zonas `geometry(MultiPolygon,4326)` + centroid geography. Features de clustering en EPSG:**25830**.
- Una dirección **activa** por paciente (índice UNIQUE parcial `is_active`).
- Una parada pertenece a **una sola ruta activa por fecha**.
- `Patient.external_ref` único por org. Sin campos clínicos.
- Dirección: `address_ciphertext` (AES-GCM). `postal_code` / `municipality` / `province` en claro (operativa/filtros). Snapshot de parada publicada: `address_snapshot_ciphertext`.
- Import: UNIQUE parcial `(organization_id, period, file_sha256)` si status ≠ `cancelled`.
- Jobs: UNIQUE `(organization_id, type, idempotency_key)`; `request_hash` SHA-256 JSON canónico. Payload sin dirección en claro.
- `share_grants` (4.BE.5): CHECK sujeto XOR `token_hash`; externo exige `expires_at`; `permission` `view`/`edit`; solo hash SHA-256 (64 hex); RLS FORCE.
- Compartición interna (4.BE.6): `POST /routes/{id}/shares` `{subject_user_id, permission}` + Idempotency-Key (`route.share`). `GET …/shares` sin token. Grant activo abre `GET /routes/{id}`. Escritura de ruta sigue siendo planner/admin (field+edit → 403).
- Compartición externa (4.BE.7): mismo POST sin `subject_user_id` + `expires_at` obligatorio; `permission=view`. Token ≥256 bit una vez; SHA-256 en BD. Canje `POST /public-shares/exchange` (sin auth). Lookup `lookup_share_grant_by_token_hash` SECURITY DEFINER. 401 inválido; 410 vencido/revocado. Vista: `sequence` únicamente (sin ref, coords, estado, paciente). Cookie `sofia_public_share` HttpOnly + `Referrer-Policy: no-referrer`.
- Revocación (4.BE.8): `DELETE /shares/{id}` 204. Invalida GET interno (403) y exchange (410) de inmediato. Outbox `share.revoked` (sin token). `audit_events` = 4.BE.11.
- Notificaciones (4.BE.9): `notifications` in-app (`unread`/`read`, UNIQUE `(event_id, recipient_id)`, RLS). Outbox `share.created` / `route.reassigned` / `plan.published` / `share.revoked`. Consumidor `consume_outbox_event` marca `processed_at`; reejecutar no duplica. Externo y revoke no crean fila in-app. Payload sin token/PII. Worker cola `notifications`. HTTP GET/PATCH = 4.BE.10.

### 4.2 Estados

| Agregado | Máquina |
|---|---|
| `ImportBatch` | `uploaded → validating → requires_correction\|validated → geocoding → ready\|failed\|cancelled` |
| Geocode | `pending → matched\|ambiguous\|not_found\|manual` |
| `MonthlyPlan` | `draft → validating → published → archived` |
| `DailyRoute` | `draft → optimizing → ready → published → in_progress → completed\|cancelled` |
| `RouteRevision` | `draft \| published` (CHECK `published_at` coherente). Inmutabilidad en **aplicación**, no trigger. |
| `Job` | `queued → running → succeeded\|failed\|cancelled` |
| `RouteStop` (ejecución, 4.BE.2) | `pending \| completed \| failed \| skipped`. If-Match = `version`. `failed` exige `failure_reason`. |
| `RouteMetric.variant` | `original \| optimized \| actual` |
| `Notification` (4.BE.9) | `unread \| read`. UNIQUE `(event_id, recipient_id)`. GET/PATCH = 4.BE.10. |

Editar una ruta `published` **no** muta la revisión: optimize / `PUT …/stops` abren `draft` nueva; `daily_routes.status` vuelve a `draft`/`ready`. Reordenar la publicada → 409 `REVISION_PUBLISHED`. Reportar ejecución (4.BE.2) solo toca columnas de parada (`status`/`completed_at`/`failure_reason`/`version`); no bumpa `daily_routes.version`. Primera parada → `in_progress`; todas `completed|failed|skipped` → `completed`.

### 4.3 Migraciones

- Alembic en `backend/alembic/versions`. Expand/contract; no depender de downgrade destructivo.
- Head reciente: `c4f1d82e90a3` (`notifications`). Lookup token: `b3e8a14c90f1`. `share_grants`: `a7c4e91b02d8`. Jobs: `d02e1f58a4c3`. Routing: `c91d0e47f3b2`. Outbox: `e4c8a2b91d07`.
- RLS en la misma oleada que la tabla (ENABLE+FORCE + policies).
- Tests de schema + RLS obligatorios al añadir tablas multi-tenant.

### 4.4 Índices (no inventar GIN)

- GiST: `addresses.location`, `zones.boundary`, `zones.centroid`, `route_stops.location`.
- B-tree: FKs, `daily_routes(service_date, assignee_id, status)`, `monthly_plans(organization_id, period, status)`, `jobs(status, created_at)`.
- No indexar JSON por defecto.

### 4.5 Routing / métricas (Fase 3)

- Matriz: coords `[origin, stop1..N, destination]`; caché Redis clave sha256 `profile\|dataset\|coords` redondeadas a **5** decimales. Celda nula/no finita aborta (bloquea publicar).
- `original` y `optimized` comparten `matrix_hash`. Reordenar o `PUT /stops` marca `calculation_json.stale = true` → comparison 409 `METRICS_STALE`.
- `actual` (4.BE.3): solo datos reportados. Coste ≈ `optimized.estimated_cost * actual.travel / optimized.travel`. `deviation.distance_m = 0` si no hay GPS.
- Optimize ledger incluye `stops_fingerprint` (pacientes + coords + `service_minutes`, **sin** orden) y `osrm_dataset_version`. Cambio de parada → clave nueva (409 si se reusa la vieja).
- `PUT /api/v1/routes/{id}/stops` `{patient_ids}` + If-Match: sustituye conjunto y refresca location desde la dirección activa confirmada (`matched`/`manual`). Máx. 25. Paciente en otra ruta activa el mismo día → 409 `STOP_ALREADY_ASSIGNED`.
- Solver inviable: `order` vacío, `diagnostics` con `INCOMPATIBLE_WINDOWS` / `ISOLATED_STOP` / `INSUFFICIENT_SHIFT` y `suggested_actions`. UI: `RouteDiagnostics` (3.FE.2). No relajar restricciones duras sin confirmación.
- Dataset OSRM: `SOFIA_OSRM_DATASET_VERSION` (default `"dev"`).

### 4.6 Planificación

- Calendario L–V, `Europe/Madrid`, festivos por config (no hardcodear BOE). Capacidad: `min(max_visits, floor(minutos / service))`. Rural: `RURAL_TRAVEL_BUFFER_MINUTES` extra en el servicio efectivo.
- Clustering: K-means urbano + DBSCAN rural, `max_visits`. Override manual con `reason`.
- `PATCH /plans/{id}/visits/{patientId}`: dry-run (`confirm` omitido) no muta; `confirm=true` + conflictos → 409. Plan publicado no se mueve (409 `PLAN_PUBLISHED`).
- Al publicar plan: assignee por defecto = `plan.created_by` salvo `body.assignees`. Rutas nacen `draft` **sin** revisión; la revisión la crea optimize.

---

## 5. Deployment rules

### 5.1 Entornos

- Dev: `docker-compose.yml` en la raíz (`sofia-dev`). Puertos solo en `127.0.0.1`. No es el compose de producción (status §3.8): sin TLS, WAF, réplicas ni backups.
- Staging/prod: mismos componentes en contenedores, reverse proxy TLS, redes privadas para db/redis/nominatim/osrm/minio, imágenes por digest, usuario no root (Dockerfile `sofia` uid 10001).
- Alta disponibilidad objetivo 99% laboral: 2 réplicas API, health checks. Una sola Postgres puede valer en piloto, no como objetivo final.
- Kubernetes: evolución futura; no cambiar el empaquetado.

### 5.2 Compose (dev) — servicios

`db` PostGIS 17-3.4 · `redis` 7 · `nominatim` extracto País Vasco · `osrm` `car.lua` MLD puerto **5001** host · `vault` **modo dev** (no prod) · `minio` · `api` :8000 · workers `imports|geocoding|zoning|planning|optimization` · `frontend` nginx+Vite.

Workers = misma imagen y **mismo env S3/cifrado** que `api`.

### 5.3 Config de aplicación

| Variable | Uso |
|---|---|
| `SOFIA_DATABASE_URL` | SQLAlchemy `postgresql+psycopg://…` |
| `SOFIA_REDIS_URL` | Cola |
| `SOFIA_NOMINATIM_BASE_URL` / `SOFIA_OSRM_BASE_URL` | Adaptadores |
| `SOFIA_OSRM_DATASET_VERSION` | Caché matriz + snapshot |
| `SOFIA_FIELD_ENCRYPTION_*` | Claves de campo (dev). Prod: Vault |
| `SOFIA_S3_*` | ObjectStore; vacío → InMemory |
| `SOFIA_TEST_DATABASE_URL` | Pytest sin testcontainers |

Nominatim público: máx. 1 req/s, User-Agent, sin PII real, sin autocomplete. Teselas OSM: atribución, sin prefetch. OSRM demo: no producción.

### 5.4 CI

`.github/workflows/ci.yml`: backend ruff + pytest (Docker) + pip-audit + build + Trivy CRITICAL/HIGH; frontend oxlint + vitest + `tsc`+vite build.

Python CI = 3.12. Node 22.

### 5.5 Runtime de contenedores en Windows (dev)

- Testcontainers habla el API Docker. Podman 5 en Windows usa **WSL2** (`podman machine`). Instalar el CLI no basta: hace falta `wsl --install` (a menudo admin + **reboot**) y `podman machine init --now`.
- Hyper-V provider de Podman exige admin.
- Comprobar: `podman run --rm alpine echo ok` antes de pytest e2e.
- En Windows, testcontainers usa el API Docker. Con Podman:

```powershell
$env:PATH = "C:\Program Files\Docker\Docker\resources\bin;C:\Program Files\RedHat\Podman;$env:PATH"
$env:DOCKER_HOST = "npipe:////./pipe/docker_engine"
$env:TESTCONTAINERS_RYUK_DISABLED = "true"
# primera vez: podman pull docker.io/postgis/postgis:17-3.4
.\.venv\Scripts\python.exe -m pytest tests/test_routing_publish_e2e.py tests/test_routing_recalc_e2e.py
```

  Ryuk suele fallar con Podman; hay que desactivarlo. Pre-pull de la imagen evita cortes del npipe al `images.pull`.
- Sin runtime: unitarios + Vitest sí; e2e de BD se skippean.

### 5.6 Operación (Fase 5, no implementar ahora)

- Migraciones: expand/contract + backup. No mezclar datos heredados con la primera carga operativa.
- OSM: extracto versionado; actualización blue/green con rutas de referencia.
- Backup PG diario + WAL/PITR cifrado; RPO 15 min / RTO 4 h (objetivo, no medido). Redis no es sistema de registro.
- Feature flags para zonificación/optimización/share externo en piloto.
- Rollback: flags off + imagen compatible; snapshots publicados siguen legibles.
- RAT/EIPD (T.RGPD.1) y ClamAV (5.SEC.7) son gates de producción, no de `[x]` de Fase 1–3.

### 5.7 Seguridad operativa ya asumida en código

- TLS 1.2+ en tránsito (prod). Cifrado de volumen + cifrado de campo.
- Contraseñas Argon2id donde hay password. MFA admin/planner = 5.SEC.5.
- Ficheros: magic bytes (no solo extensión), límite de tamaño, nombres generados, sin macros. Antivirus = 5.SEC.7.
- Share externo (Fase 4): token ≥256 bit, solo hash en BD, caducidad, revocación, vista minimizada, `Referrer-Policy: no-referrer`.

---

## 6. Endpoints de routing ya existentes (no redefinir)

| Método | Ruta | Notas |
|---|---|---|
| GET | `/api/v1/jobs/{id}` | Progreso durable (3.FE.1). Query `organization_id`. 404 si no es de la org. |
| POST | `/api/v1/routes/{id}/optimize` | 202, `Idempotency-Key`, cola `optimization` |
| GET | `/api/v1/routes/{id}` | Detalle + diagnostics. Planner/admin, field asignado, o **grant interno activo** (4.BE.6). |
| POST | `/api/v1/routes/{id}/shares` | Interna (`subject_user_id`) o externa (`expires_at`, token una vez). Idempotency-Key. Planner/admin. |
| GET | `/api/v1/routes/{id}/shares` | Grants activos **sin** token. Planner/admin. |
| POST | `/api/v1/public-shares/exchange` | Token → vista minimizada + cookie. 401/410. Sin auth. |
| DELETE | `/api/v1/shares/{id}` | 204 revoca (`revoked_at`). Planner/admin. Query `organization_id`. 409 si ya revocada. |
| GET | `/api/v1/routes/{id}/comparison` | original/optimized/savings + `original_stops`/`optimized_stops`. Si hay ejecución: `actual`, `deviation` (actual − optimized) y `execution_counts`. 409 `METRICS_STALE` / `METRICS_UNAVAILABLE`. Distancia actual no se infiere (GPS v1 no). |
| PATCH | `/api/v1/routes/{id}/stops/order` | If-Match = `daily_routes.version`, métricas stale |
| PUT | `/api/v1/routes/{id}/stops` | If-Match = `daily_routes.version`, sustituir paradas (3.BE.9) |
| PATCH | `/api/v1/routes/{id}/stops/{stopId}` | Ejecución (4.BE.2). If-Match = **`route_stops.version`**. Body `status`/`completed_at`/`failure_reason`. Planner/admin o field asignado. 409 `STOP_VERSION_CONFLICT` + `errors[0]` estado más reciente. No muta snapshot. |
| POST | `/api/v1/routes/{id}/publish` | 200, If-Match + Idempotency-Key, snapshot (3.BE.11) |
| POST | `/api/v1/routes/{id}/exports` | 202, `format: pdf\|png\|navigation_link`, Idempotency-Key, cola `exports`. Solo revisión publicada. Enlace Google Maps **solo coords**. PDF/PNG esquemáticos (sin teselas OSM). |
| GET | `/api/v1/jobs/{id}/artifact` | Descarga PDF/PNG desde ObjectStore |
| GET | `/api/v1/history/routes` | Snapshots `published`. Query `from`,`to`,`zone`,`assignee`,`patient_ref`,`cursor`,`limit`. Campo solo ve sus rutas. |

`PATCH /routes/{id}/stops/{stopId}` (ejecución) es **4.BE.2 `[x]`**. No reutilizarlo para editar el conjunto de paradas. Comparativa `variant=actual` es **4.BE.3 `[x]`**: upsert al reportar; viaje = span `completed_at` de completed|failed − servicio completado; skipped no viaja; `distance_m=0` (`distance_source=unavailable`). Plan = métricas `optimized`. UI de histórico = **4.FE.1 `[x]`** (`/historico`, snapshots con `external_ref`, no el paciente vivo).

---

## 7. Qué no hacer

- No cerrar 1.FE.8 sin informe de usuarios reales.
- No tratar `[x]` como production-ready (falta DoD PR, ClamAV, usabilidad, RGPD).
- No mutar una `route_revisions` `published`.
- No relajar ventanas/jornada VRPTW sin confirmación explícita.
- No usar Haversine como estimación vial silenciosa (sí para propuesta/degradación marcada).
- No enviar PII a Nominatim/OSRM/teselas de terceros en producción.
- No añadir Playwright, Kafka, GraphQL, Kubernetes o proveedor de mapas de pago “por si acaso”.
- No reescribir el diseño entero para cada delta: status §3 + este fichero.
