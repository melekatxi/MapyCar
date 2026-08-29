# Instrucciones para GitHub Copilot — App de Rutas de Visitas a Pacientes

> Este repositorio aún no tiene código fuente: contiene la documentación de contexto (requisitos, propuesta, diseño y tareas) que define cómo debe construirse la aplicación. Estas instrucciones preparan el terreno para cuando empiece la implementación siguiendo el plan de tareas.

## 1. Resumen del proyecto

Aplicación web (con vista adaptada a móvil) para **planificar y optimizar rutas de visitas domiciliarias a pacientes**. Permite importar mensualmente un listado de ~200 pacientes desde Excel/CSV, geocodificar sus direcciones, agruparlas en zonas geográficas, planificar visitas diarias, calcular la ruta óptima (tiempo o coste) por zona/día, generar mapas de ruta, mantener un histórico consultable y compartir rutas entre usuarios con control de permisos.

Los usuarios tratan **datos de salud/pacientes** (categoría especial de datos bajo RGPD), por lo que privacidad, minimización y seguridad son requisitos de primer orden, no opcionales.

## 2. Stack tecnológico

| Capa | Tecnología |
|---|---|
| Frontend | React + TypeScript, Leaflet + teselas OpenStreetMap, diseño responsive (desktop y móvil/tablet) |
| Backend | Python + FastAPI, monolito modular con workers separados |
| Base de datos | PostgreSQL 17 + PostGIS |
| Cola/cache | Redis (colas de trabajos: imports, geocoding, zoning, routing, optimization, exports, notifications) |
| Geocodificación | Nominatim (OpenStreetMap) autoalojado |
| Cálculo de rutas/distancias | OSRM (Open Source Routing Machine) autoalojado |
| Optimización de rutas (TSP/VRP) | Google OR-Tools |
| Infraestructura | Docker + Docker Compose en **todos** los entornos (dev, staging, producción); sin Kubernetes ni PaaS de pago como requisito inicial |

Todos los componentes (frontend, API, workers, PostgreSQL/PostGIS, Redis, Nominatim, OSRM) se ejecutan siempre como contenedores Docker, sin instalación directa sobre el host.

## 3. Decisiones arquitectónicas clave (ADR)

- **ADR-01**: Monolito modular FastAPI/Python con workers separados (no microservicios desde el inicio; no NestJS).
- **ADR-02**: React + TypeScript + Leaflet, responsive, sin dependencia de Mapbox/Google Maps como base.
- **ADR-03**: REST JSON bajo `/api/v1` con OpenAPI (no GraphQL).
- **ADR-04**: PostgreSQL 17 + PostGIS como sistema de registro (geometría e índices geoespaciales nativos).
- **ADR-05**: Redis + cola de trabajos para tareas asíncronas (importación, geocodificación, matrices, optimización, exportación).
- **ADR-06**: Adaptadores desacoplados `Geocoder`, `Router`, `Optimizer`, `TileProvider`, `ObjectStore` (patrón *adapter*) — nunca invocar proveedores externos directamente desde controladores.
- **ADR-07**: Nominatim y OSRM autoalojados con extracto OSM de Euskadi/norte peninsular (no APIs públicas de pago por defecto).
- **ADR-08**: Rutas publicadas como **snapshots versionados e inmutables**; cualquier cambio posterior crea una revisión nueva.
- **ADR-09**: Seudónimo operativo (`external_ref`/`display_ref`) y dirección cifrada por campo (AES-256-GCM); nunca nombre completo del paciente en toda la aplicación.
- **ADR-10**: Optimización en dos etapas — matriz de distancias/tiempos vía OSRM + resolución TSP/VRP con OR-Tools.
- **ADR-11**: Ejecución 100% en contenedores Docker en todos los entornos vía Docker Compose.

## 4. Convenciones que debe respetar todo código nuevo

### API
- Base `/api/v1`, JSON UTF-8, IDs en formato UUID (UUIDv7 para PKs), fechas ISO 8601, paginación por cursor.
- `Idempotency-Key` **obligatorio** en operaciones de importación, commit, optimización, publicación, exportación y compartición. El servidor debe rechazar (409) una clave reutilizada con payload distinto.
- `ETag` / `If-Match` obligatorios para escritura sobre zonas, planes, rutas y paradas; escribir sobre una versión antigua debe devolver 409.
- Correlación de peticiones vía `X-Request-ID` (nunca debe contener identificadores de paciente).
- Formato de error estándar: `type/title/status/code/detail/instance/request_id/errors[]` (problem details extendido).
- Trabajos largos devuelven `202 Accepted` + `job_id` + `status_url` + `Retry-After`.

### Datos y multi-tenancy
- Toda tabla de negocio incluye `organization_id UUID NOT NULL`; el aislamiento se refuerza con **Row Level Security (RLS)** en PostgreSQL, no solo con filtros de aplicación.
- No modelar dato clínico alguno; solo referencia operativa, dirección y restricciones horarias imprescindibles (principio de minimización).
- Direcciones y datos de contacto se cifran por campo (AES-256-GCM) además del cifrado de volumen/disco.
- Las rutas publicadas son snapshots inmutables: no se sobrescriben, se versionan (`route_revisions`).
- Todas las tablas relevantes con auditoría append-only (`audit_events`), nunca borrado ni edición retroactiva de eventos.

### Seguridad y privacidad (RGPD/LOPDGDD)
- Datos de pacientes = categoría especial de datos de salud. Cifrado en tránsito (TLS 1.2+) y en reposo obligatorio.
- RBAC por organización con roles `admin`, `planner`, `field`, `supervisor`; el frontend oculta acciones por ergonomía pero **el backend siempre re-autoriza cada petición**.
- Nunca enviar nombre/referencia real del paciente a servicios de geocodificación externos; solo dirección mínima necesaria.
- Enlaces de compartición externos: token de ≥256 bits (solo se persiste su hash), expiración obligatoria, revocación, vista minimizada (oculta nombre/referencia y datos sensibles por defecto).
- Toda acción de creación, edición, borrado, publicación, exportación o compartición de datos de pacientes/rutas debe emitir un evento de auditoría.
- Los proveedores de pago (Google Maps, Mapbox, etc.) están **desactivados por defecto** y solo se habilitan por configuración explícita, con aprobación del responsable — nunca como comportamiento por defecto en el código.

### Infraestructura
- Todo se empaqueta y ejecuta como contenedor Docker en dev/staging/producción, orquestado con Docker Compose. No introducir dependencias que requieran instalación directa sobre el host o servicios PaaS de pago.
- Solo el reverse proxy publica puertos; PostgreSQL, Redis, Nominatim, OSRM y almacenamiento permanecen en red privada.

## 5. Restricciones importantes (no negociables sin aprobación explícita)

- **Nada de servicios de pago por defecto**: la propuesta base usa exclusivamente componentes open source autoalojados (OpenStreetMap + Nominatim + OSRM + OR-Tools). Un proveedor de pago solo se activa como excepción configurable y aprobada.
- **Todo en Docker**: sin excepciones, en los tres entornos.
- **Minimización y seudonimización de datos de pacientes**: usar referencia/seudónimo en lugar de nombre completo siempre que sea posible; no almacenar datos clínicos.
- **Snapshots inmutables**: una ruta publicada nunca se edita in situ; los cambios generan una revisión nueva.
- **Auditoría obligatoria**: cualquier operación sensible sobre datos de pacientes o rutas debe quedar registrada (usuario, acción, fecha/hora).

## 6. Documentos fuente

- [Requisitos](../docs/requisitos/requisitos-app-rutas-pacientes.md)
- [Propuesta técnica y funcional](../docs/propuesta/propuesta-app-rutas-pacientes.md)
- [Diseño técnico](../docs/diseno/diseno-app-rutas-pacientes.md)
- [Desglose de tareas](../docs/tareas/tareas-app-rutas-pacientes.md)

Ante cualquier duda de diseño, convención de API/datos o alcance, consulta primero estos documentos antes de improvisar una solución.
