# Protocolo de pruebas de usabilidad — Fase 1 (asistente de importación y mapa)

| Campo | Valor |
|---|---|
| Tarea | **1.FE.8** (abierta) |
| Requisito | [RNF-07](../requisitos/requisitos-app-rutas-pacientes.md): la interfaz de mapa y planificación debe ser utilizable por usuarios no técnicos, con formación mínima |
| Alcance de producto | MVP Fase 1: importación → corrección → geocodificación → mapa operativo ([1.FE.1](../../frontend/src/imports/ImportWizardPage.tsx), [1.FE.2](../../frontend/src/imports/ImportProgressPage.tsx), [1.FE.3](../../frontend/src/geocoding/GeocodingTrayPage.tsx), [1.FE.4](../../frontend/src/map/OperationalMapPage.tsx), [1.FE.7](../../frontend/src/index.css)) |
| Criterio de 1.FE.8 | Informe de usabilidad con hallazgos y **≤ 2 bloqueantes críticos sin resolver** |
| Estado de este documento | **Protocolo.** No es el informe. No cierra 1.FE.8. |

## Advertencia — este fichero no satisface 1.FE.8

Este documento es el **guion para ejecutar** sesiones con personas reales. **No** sustituye esas sesiones.

- **Prohibido** rellenar el informe con participantes ficticios, citas inventadas o “hallazgos de IA”.
- **Prohibido** marcar 1.FE.8 como hecha al publicar este protocolo.
- 1.FE.8 queda **abierta** hasta que exista un informe firmado, con sesiones reales, tabla de hallazgos y recuento de bloqueantes no resueltos.

Validación de diseño (sección 15.2): RNF-07 se valida con **pruebas de usabilidad con perfiles reales**, no con E2E automáticos (1.QA.1 no cubre este requisito).

---

## 1. Objetivo

Comprobar si un usuario **no técnico** de un equipo de visitas domiciliarias puede, con formación mínima (este protocolo: ≤ 2 minutos de contexto, sin tutorial de producto):

1. Subir el listado mensual (CSV, XLSX o XLS).
2. Entender (o echar en falta) el mapeo de columnas.
3. Corregir una fila inválida y confirmar la carga.
4. Resolver una dirección en la bandeja de geocodificación.
5. Localizar y confirmar un punto en el mapa operativo.
6. Repetir lo esencial en viewport móvil.

La pregunta de investigación no es “¿el backend funciona?” (eso ya lo cubren 1.QA.1 / 1.QA.2). Es: **¿el flujo guiado y el mapa son utilizables sin un técnico al lado?**

## 2. Audiencia y reclutamiento

**Perfil objetivo (RNF-07):** usuarios no técnicos de equipos de visitas domiciliarias.

| Perfil | Mínimo | Rol en Sofia (Fase 1) | Qué se observa |
|---|---|---|---|
| Coordinador / planificador de equipo | 3 | `planner` | Importación, corrección, bandeja, mapa |
| Visitador / usuario de campo | 2 | `field` | Mapa, detalle de punto, viewport móvil |

- **N recomendado:** 5–8 participantes (mínimo 5; no menos de 2 de campo).
- **Incluir:** personas que hoy planifican o visitan con Excel/papel, sin formación en GIS ni en esta app.
- **Excluir:** desarrolladores del proyecto, testers que ya conocen el flujo, y quien haya implementado 1.FE.*.
- **No hace falta** que sepan qué es Nominatim, Leaflet ni un CSV con cabeceras canónicas. Si lo saben, anótalo: sesgo.

Formación mínima permitida **antes** de la Tarea 1: frase de contexto (ver script). Nada de “pulsa aquí, luego aquí”.

## 3. Criterio de cierre de 1.FE.8 (después de las sesiones)

El informe final **cierra** 1.FE.8 solo si se cumplen **todas** estas condiciones:

1. Al menos **5** sesiones reales con el perfil de la sección 2, documentadas (fecha, identificador anónimo, perfil, tareas).
2. Tabla de hallazgos con severidad, evidencia (cita o observación) y propuesta.
3. Recuento de **bloqueantes críticos sin resolver ≤ 2**.
4. Firma del facilitador (o responsable de QA) y fecha.

Si hay **más de 2** bloqueantes abiertos, 1.FE.8 sigue abierta: hay que corregir producto y **repetir** al menos las tareas afectadas (no basta con “lo arreglaremos”).

## 4. Contexto de producto (el facilitador debe conocerlo; el participante no)

Estado real a 2026-08-30. No se lo expliques al participante salvo que se atasque y hayas agotado la espera (entonces es **ayuda de facilitador**, se anota y la tarea no cuenta como éxito autónomo).

| Hecho | Implicación para la prueba |
|---|---|
| El asistente (`/importar`) pide **periodo (AAAA-MM)** y **fichero**. `accept=".csv,.xlsx,.xls"`. No hay selector de equipo. | Si el participante busca “equipo”, anótalo; no es fallo suyo. `.xls` **sí** está aceptado. |
| **No hay pantalla de mapeo de columnas.** El backend usa cabeceras canónicas (`id_paciente`, `nombre_referencia`, `direccion`, `codigo_postal`, `municipio`, `provincia`, `tipo_zona`). El diseño 3.2 sí prevé mapeo; 1.FE.1 lo deja “por defecto”. | La Tarea 3 existe precisamente para ver si el usuario echa en falta el mapeo. Un atasco aquí puede ser bloqueante de producto, no de la persona. |
| Tras subir, navega a `/importar/:batchId`: estado, conteos, tabla de errores, **Corregir**, **Confirmar filas válidas**, **Geocodificar pacientes confirmados**. | La corrección solo edita campos con error (p. ej. CP). |
| La bandeja (`/geocodificacion`) lista solo `ambiguous` y `not_found`. Motivo obligatorio. Candidatos en globo Leaflet o clic para marcador manual. Solo `external_ref`, nunca el nombre real (ADR-09). | Si todas las filas salen `matched`, la bandeja queda vacía: usar el fixture con PAC-051 / PAC-058. |
| El mapa (`/mapa`) tiene **dos leyendas**: (1) estado de visita pendiente / planificada / completada (relleno; hoy **todos** `pending` hasta `DailyRoute`); (2) geocodificación (borde: pendiente / geocodificada / ambigua / no encontrada / manual). El panel muestra referencia, municipio, CP, provincia, confianza, día/zona = **Sin asignar**; **no** la calle (ADR-09). 1.FE.5/1.FE.6 cerrados como MVP RF-07/RF-08. | No pidas al usuario que distinga “visita completada” como dato real. Si usa las dos leyendas, anota si confunde geocodificación con visita hecha. |
| Responsive 1.FE.7: `@media (max-width: 768px)` colapsa el menú (botón **Menú**) y pasa mapa/bandeja a una columna. | Viewport de Tarea 8: 375×667 o dispositivo real. |
| Login: correo + contraseña. No hay alta self-service. | Cuenta de prueba preparada por el equipo; no datos reales de pacientes. |

## 5. Preparación (antes del primer participante)

### 5.1 Entorno

- App desplegada en un entorno **estable** (local Docker o staging). Misma build para todos los participantes.
- Cuenta de prueba rol `planner` (importación) y, si es posible, una de `field` (solo mapa). Credenciales en papel o gestor, no en este repo.
- Worker de importación y de geocodificación **en marcha**. Nominatim local si se va a geocodificar de verdad.
- Grabación opcional de pantalla + voz con consentimiento. Si no hay grabación, un observador toma notas literales.
- Cronómetro. Plantillas de la sección 11 impresas o en un doc vacío **por sesión**.

### 5.2 Ficheros de prueba (datos ficticios)

Usar **solo** dataset ficticio de Bizkaia. Nunca un Excel real de pacientes.

| Fichero | Origen | Uso |
|---|---|---|
| A — XLSX canónico | Copia de [`docs/requisitos/direcciones-ejemplo-bizkaia.xlsx`](../requisitos/direcciones-ejemplo-bizkaia.xlsx) recortada a ~15–25 filas, **incluyendo PAC-051 y PAC-058** | Tarea 2 (carga “feliz”) y bandeja |
| B — CSV con error | Misma slice en CSV `;` con **una** fila cuyo `codigo_postal` no tenga 5 dígitos (p. ej. `48`) | Tarea 4 (corregir) |
| C — CSV con cabeceras “humanas” | Mismos datos, cabeceras tipo `ID paciente`, `Dirección`, `CP`, `Municipio`, `Provincia` | Tarea 3 (mapeo). El producto **hoy no mapea**; el hallazgo es si el usuario se recupera o se rinde |
| D — CSV canónico pequeño | 5–8 filas, cabeceras exactas, un CP inválido, PAC-051 | Sesión corta / móvil si el tiempo aprieta |

Periodo a usar en la UI: un mes futuro que **no** se haya importado ya (la deduplicación `file_sha256 + periodo` devuelve 409). Cada participante: periodo distinto o fichero ligeramente distinto.

### 5.3 Datos de sesión (RGPD)

- Identificar participantes como P1, P2… Nunca nombre en el informe público.
- Consentimiento informado: la sesión se observa; se puede parar; no hay evaluación de su trabajo.
- No introducir datos personales reales de pacientes.

## 6. Roles en la sala

| Rol | Hace | No hace |
|---|---|---|
| **Facilitador** | Lee el script, da las tareas de una en una, espera, anota ayudas | No enseña la UI, no defiende el diseño, no dice “es fácil” |
| **Observador** (recomendado) | Cronometra, anota literal, marca éxito/fallo | No habla con el participante |
| **Participante** | Piensa en voz alta y usa la app | No tiene que “acertar” |

## 7. Script del facilitador

### 7.1 Antes (≤ 2 min de contexto)

> Gracias por venir. Vamos a probar una herramienta de planificación de visitas a domicilio que todavía está en construcción. **No te evaluamos a ti**: evaluamos si la herramienta se entiende. No hay respuestas correctas. Habla en voz alta: qué buscas, qué esperas, qué te extraña. Yo no te diré qué pulsar salvo que te quedes bloqueado de verdad. Puedes parar cuando quieras. Los listados son **ficticios**.

Preguntas de calentamiento (30 s):

1. ¿Usas Excel o papel para las rutas de visitas?
2. ¿En qué dispositivo trabajas más: ordenador, tablet o móvil?

### 7.2 Durante cada tarea

1. Leer el escenario **tal cual** (sección 8). Entregar el fichero si aplica. No adelantar el siguiente paso.
2. Callar. Esperar **10–15 s** de silencio antes de cualquier pista.
3. Si pide ayuda: primero “¿qué estarías intentando hacer en tu trabajo?”. Segunda pista: señalar la zona de la pantalla, no el botón. Tercera: desbloquear y **marcar la tarea como fallida con ayuda**.
4. Al terminar: “¿Listo/a? ¿Qué te ha resultado más confuso de esto?”

**Frases prohibidas:** “es intuitivo”, “ahora mapeas las columnas”, “el verde es geocodificada”, “pulsa Confirmar filas válidas”.

### 7.3 Después (3–5 min)

1. En una escala de 1 (muy difícil) a 7 (muy fácil), ¿cómo de fácil ha sido cargar el listado?
2. ¿Y ver a los pacientes en el mapa?
3. Si tuvieras que formar a un compañero en 5 minutos, ¿qué le dirías que **no** va a entender?
4. ¿Echas en falta algo imprescindible para tu trabajo este mes? (zonas, calendario, ruta del día: anotar; **Fase 2/3**, no son fallos de 1.FE.8 salvo que impidan el mapa/importación).

Agradecer. No prometas plazos de arreglo.

## 8. Tareas (8)

Duración objetivo por sesión: **35–45 min** (tareas 1–7 en desktop ~1280×800; tarea 8 en móvil). Si hay que recortar: 2, 4, 6, 7, 8.

Cada tarea: escenario (se lee), éxito autónomo, fallo, notas de observación.

### Tarea 1 — Entrar y encontrar el flujo de importación

**Escenario:** *Acabas de recibir el listado del mes. Entra en Sofia y llega hasta donde se carga ese listado.*

| | |
|---|---|
| Punto de partida | `/login` → tras acceso, la app abre en `/mapa` |
| Éxito | Encuentra **Importar** (menú) y ve el formulario “Importar pacientes” sin ayuda de tercer nivel |
| Fallo | No encuentra Importar en 3 min; o no entiende que debe identificarse |
| Observar | ¿El mapa inicial confunde (“¿esto ya está cargado?”)? ¿El botón **Menú** en viewport estrecho? |

### Tarea 2 — Subir CSV, XLSX o XLS

**Escenario:** *Carga el listado de este mes. Usa el fichero A (xlsx) o D (csv). El periodo es [AAAA-MM que indiques].*

| | |
|---|---|
| Éxito | Elige periodo, adjunta fichero, pulsa **Subir e iniciar validación** y llega a la página de progreso con estado/conteos |
| Fallo | No completa la subida; no entiende “periodo”; elige un formato rechazado y abandona; no percibe el error |
| Observar | ¿Usa .xls y el selector lo admite? ¿Busca mapeo o equipo antes de subir? ¿El texto “máximo 500 filas” ayuda o asusta? |

Alternar CSV y XLSX entre participantes (RNF-09). El wizard **sí** acepta `.xls` (`accept=".csv,.xlsx,.xls"`): si alguien llega con .xls, debe poder seleccionarlo; si el diálogo del SO lo oculta, anotar. No hace falta inventar un fixture .xls para todas las sesiones.

### Tarea 3 — Mapear / reconocer columnas

**Escenario:** *Antes de dar por buena la carga, confirma que las columnas del Excel (identificador, dirección, código postal, municipio, provincia) han quedado bien asignadas. Si la pantalla no te deja asignarlas, di en voz alta qué echas en falta y qué harías con el fichero C (cabeceras “humanas”).*

| | |
|---|---|
| Éxito | El participante **entiende el estado real**: o bien verifica que las cabeceras canónicas bastan, o bien articula con claridad que no puede mapear y qué haría (renombrar Excel, pedir ayuda). No se rinde en silencio. |
| Fallo | Cree que el sistema “adivina” columnas distintas y sigue; o se bloquea >3 min sin estrategia; o publica datos mal alineados sin darse cuenta |
| Observar | Expectativa de un desplegable columna a columna (diseño 3.2). Lenguaje de errores si usa el fichero C. Esto es un **probe de producto**, no un truco al usuario. |

### Tarea 4 — Corregir una fila

**Escenario:** *El listado B tiene al menos una fila mal. Encuéntrala, corrígela y deja esa fila válida.*

| | |
|---|---|
| Éxito | Localiza la tabla de errores, pulsa **Corregir**, arregla el campo (p. ej. CP a 5 dígitos), **Guardar**, y la fila deja de aparecer como inválida (o entiende el nuevo conteo) |
| Fallo | No ve los errores; no entiende `codigo_postal: …`; edita y no guarda; corrige el campo equivocado |
| Observar | Códigos de error vs. frase humana. ¿Descarga el CSV de errores? ¿Echa en falta ver la dirección completa al corregir? |

### Tarea 5 — Confirmar carga y lanzar geocodificación

**Escenario:** *Cuando las filas que te importan estén bien, confirma la carga y pide al sistema que sitúe las direcciones en el mapa.*

| | |
|---|---|
| Éxito | Pulsa **Confirmar filas válidas**, percibe el mensaje de pacientes confirmados, pulsa **Geocodificar pacientes confirmados** y entiende que debe ir a la bandeja o esperar |
| Fallo | Confirma sin haber corregido y no se da cuenta; no encuentra “geocodificar”; interpreta “encolada” como error |
| Observar | Dos botones juntos (confirmar vs. geocodificar). Vocabulario “geocodificación”. |

### Tarea 6 — Bandeja de geocodificación

**Escenario:** *Hay direcciones que el sistema no ha colocado con seguridad (por ejemplo un caserío o un barrio). Ábrelas, elige un candidato o coloca el punto a mano, y confirma con un motivo.*

| | |
|---|---|
| Punto de partida | `/geocodificacion`. Debe haber al menos un `ambiguous` / `not_found` (PAC-051, PAC-058). |
| Éxito | Abre una referencia, usa el mapa (globo **Elegir este candidato** o clic + **Confirmar marcador manual**), rellena **Motivo**, ve el mensaje de confirmación |
| Fallo | No encuentra la bandeja; no abre el globo del marcador; no entiende que el motivo es obligatorio; no sabe clicar el mapa; confirma el punto equivocado sin mirar |
| Observar | Lista en inglés (`ambiguous`, `not_found`). Motivo sin ejemplos. Solo referencia operativa, no nombre. Leaflet en móvil. |

### Tarea 7 — Confirmar en el mapa operativo

**Escenario:** *Ve al mapa de pacientes. Encuentra un punto ya situado, selecciónalo y dime si está en el municipio/CP que esperas. Usa las leyendas si te sirven.*

| | |
|---|---|
| Éxito | Navega a **Mapa**, hace zoom/pan, pulsa un punto, lee el panel (referencia, municipio, CP, estado de visita, geocodificación, día/zona) y **verbaliza** si le encaja |
| Fallo | No encuentra el mapa o los puntos; no entiende las dos leyendas; no asocia color con estado; no puede seleccionar en móvil |
| Observar | ¿Busca el nombre del paciente o la calle? (ADR-09: no están). ¿Busca zonas o “ruta de hoy”? (Fase 2; día/zona = Sin asignar). ¿Confunde “Geocodificada” con “visita hecha”? Hoy todas las visitas están pendientes. |

### Tarea 8 — Viewport móvil

**Escenario:** *Estás en la calle con el teléfono. Abre el menú, entra al mapa, selecciona un punto y (si hay tiempo) mira si podrías cargar un listado desde el móvil.*

| | |
|---|---|
| Viewport | Ancho ≤ 768 px (p. ej. 375×667) o dispositivo real. No “responsive mode” a 900 px. |
| Éxito | Encuentra **Menú**, llega a Mapa, selecciona un punto y lee el detalle en una columna sin perder el mapa del todo; el flujo no se rompe (botones a mano, sin scroll horizontal de la app) |
| Fallo | No encuentra la navegación; el mapa no responde al dedo/clic; el detalle tapa todo y no se puede volver; importar es inutilizable (teclado, `type="file"`, tabla de errores) |
| Observar | Importar en móvil es **secundario** para campo (RNF-08 prioriza consulta). Si importar es imposible en móvil, severidad **grave** para planificadores móviles, **menor** si el planificador declara que solo usa desktop. |

## 9. Criterios de éxito y fallo (sesión y estudio)

### 9.1 Por tarea (marcar una)

| Resultado | Definición |
|---|---|
| **Éxito autónomo** | Completa el objetivo sin pistas de segundo o tercer nivel |
| **Éxito con ayuda** | Completa tras 1–2 pistas. **No** cuenta como éxito para el umbral de 1.FE.8 |
| **Fallo** | Abandona, error irreversible, o necesita que el facilitador ejecute el paso |
| **No aplicable** | El entorno no permitió la tarea (bandeja vacía, 409, worker caído). **Repetir** la tarea; no puntuar |

Tiempo de referencia (no son límites duros; sí son señales):

| Tarea | Señal de fricción si supera |
|---|---|
| 1 Entrar / Importar | 2 min |
| 2 Subir fichero | 3 min |
| 3 Columnas | 4 min |
| 4 Corregir fila | 4 min |
| 5 Confirmar + geocodificar | 3 min |
| 6 Bandeja | 5 min |
| 7 Mapa | 3 min |
| 8 Móvil | 5 min |

### 9.2 Estudio (informe)

Para **cerrar** 1.FE.8, además de N≥5 y el recuento de bloqueantes:

- Tareas **2, 4, 6 y 7** con tasa de **éxito autónomo ≥ 4/5** de quienes las intentaron (o ≥ 80 % si N>5).
- Tarea **3**: no se exige éxito de “mapear en UI” (la UI no existe). Sí se exige documentar el hallazgo y clasificarlo. Si ≥ 3 participantes no pueden cargar un Excel con cabeceras reales de su equipo, tratarlo como **bloqueante** hasta que haya mapeo o plantilla descargable inequívoca.
- Tarea **8**: al menos el mapa debe ser éxito autónomo en ≥ 4/5; importar en móvil puede quedar como grave/menor según perfil.

Estos umbrales no se rellenan hasta tener sesiones. Dejar las celdas vacías es correcto.

## 10. Escala de severidad

Un hallazgo = un problema observado **en al menos un participante real**, con evidencia.

| Severidad | Definición | Ejemplo de tipo (no son hallazgos reales) |
|---|---|---|
| **Bloqueante** (crítico) | Impide completar el flujo de importación o de ver/confirmar el mapa **sin** un técnico. Afecta a la pregunta de RNF-07. | No se encuentra cómo subir; no se puede corregir una fila; el mapa no se puede usar en el dispositivo de campo; columnas del Excel real no entran y no hay salida |
| **Grave** | Se completa con mucho esfuerzo, error fácil o trabajo extra recurrente. Formación mínima no basta. | Errores en código (`INVALID_POSTAL_CODE`) incomprensibles; motivo obligatorio invisible; leyenda no se entiende |
| **Menor** | Molestia cosmética o de copy; hay workaround evidente | Palabra “geocodificación”; inglés en estados; periodo `type="month"` poco familiar |

**No es hallazgo de 1.FE.8** (anotar en “fuera de alcance / Fase 2+”):

- Falta de zonas, calendario, ruta del día, **datos** reales planificada/completada y RBAC de campo (`2.BE.14` / `ShareGrant`). Las leyendas MVP de 1.FE.5 y el detalle RF-08 de 1.FE.6 **sí** están; no exigir que un `field` vea solo lo asignado ni que haya visitas completed de verdad.
- Rendimiento de 200 direcciones (RNF-01, ya medido).
- Fallos de entorno (Docker caído, Nominatim timeout): repetir, no puntuar al producto.

**Agrupar** el mismo problema visto en varios participantes en **un** hallazgo (indicar n). No inflar recuento.

**Bloqueante sin resolver** = sigue en el producto el día del informe. Un parche desplegado y **re-probado** con al menos 2 usuarios del perfil deja de contar.

## 11. Plantilla por sesión (copiar una vez por participante)

Dejar en blanco hasta la sesión. No rellenar con ejemplos inventados.

```
Sesión: P__     Fecha: ____-__-__     Perfil: planificador / campo
Dispositivo: desktop / tablet / móvil     Viewport: ______
Ficheros usados: A / B / C / D     Periodo: ______
Consentimiento: sí / no     Grabación: sí / no
Facilitador: ______     Observador: ______
```

| Tarea | Resultado (autónomo / con ayuda / fallo / N/A) | Tiempo | Pistas (n) | Notas literales |
|---|---|---|---|---|
| 1 Entrar / Importar |  |  |  |  |
| 2 Subir CSV/XLSX/XLS |  |  |  |  |
| 3 Columnas |  |  |  |  |
| 4 Corregir fila |  |  |  |  |
| 5 Confirmar + geocode |  |  |  |  |
| 6 Bandeja |  |  |  |  |
| 7 Mapa |  |  |  |  |
| 8 Móvil |  |  |  |  |

Citas (textual):

-

Facilidad percibida (1–7): importación __    mapa __

Incidentes de entorno (no puntúan):

-

## 12. Plantilla del informe final (evidencia de 1.FE.8)

Crear **después** de las sesiones reales, por ejemplo `docs/qa/usabilidad-fase1-informe.md`. No existe hasta entonces. No copiar esta plantilla rellena con datos falsos.

### 12.1 Portada

| Campo | Valor |
|---|---|
| Título | Informe de usabilidad Fase 1 — Sofia |
| Tarea | 1.FE.8 / RNF-07 |
| Fechas de sesiones | |
| N participantes |  (desglose planificador / campo) |
| Build / entorno | |
| Facilitador | |
| Bloqueantes abiertos | **n / ≤ 2 para cerrar** |
| Decisión | **1.FE.8 abierta** / **1.FE.8 cerrada** (solo si n≤2 y N≥5) |

### 12.2 Resumen ejecutivo (máx. ½ página)

- Qué se probó.
- Tasa de éxito autónomo por tarea (tabla).
- Los 3 problemas más costosos.
- Decisión sobre RNF-07 en el MVP.

### 12.3 Método

- Enlace a este protocolo.
- Cómo se reclutó. Cualquier desviación (p. ej. 4 participantes en vez de 5) → **no cerrar** 1.FE.8.

### 12.4 Resultados por tarea

| Tarea | n | Éxito autónomo | Con ayuda | Fallo | N/A |
|---|---|---|---|---|---|
| 1 |  |  |  |  |  |
| 2 |  |  |  |  |  |
| 3 |  |  |  |  |  |
| 4 |  |  |  |  |  |
| 5 |  |  |  |  |  |
| 6 |  |  |  |  |  |
| 7 |  |  |  |  |  |
| 8 |  |  |  |  |  |

### 12.5 Tabla de hallazgos

| ID | Hallazgo | Tarea | n | Severidad | Evidencia (cita o observación) | Propuesta | Estado (abierto / resuelto + retest) |
|---|---|---|---|---|---|---|---|
| U-01 |  |  |  | bloqueante / grave / menor |  |  |  |

### 12.6 Recuento de bloqueantes

| | n |
|---|---|
| Bloqueantes encontrados |  |
| Resueltos y re-probados |  |
| **Bloqueantes críticos sin resolver** |  **← debe ser ≤ 2 para cerrar 1.FE.8** |

Lista explícita de los no resueltos:

1.
2.

### 12.7 Fuera de alcance (Fase 2+)

Hallazgos sobre zonas, calendario, rutas, estados de visita, permisos de campo.

### 12.8 Anexos

Hojas de sesión P1…Pn. Sin nombres reales.

---

## 13. Lista de comprobación del facilitador (día de prueba)

- [ ] Entorno arriba; worker de import/geocode vivo
- [ ] Cuentas de prueba; periodos libres
- [ ] Ficheros A/B/C (o D) en un USB/carpeta, **ficticios**
- [ ] Al menos un `not_found` previsto (PAC-051 / PAC-058)
- [ ] Plantilla de sesión vacía por participante
- [ ] Consentimiento
- [ ] Viewport móvil listo
- [ ] Este protocolo a mano; **informe aún vacío**

## 14. Relación con otras tareas

| ID | Relación |
|---|---|
| 1.QA.1 / 1.QA.2 | Pruebas automáticas de flujo y formatos. **No** equivalen a 1.FE.8 |
| 1.FE.7 | Responsive implementado; 1.FE.8 lo valida con personas (Tarea 8) |
| 1.FE.5 / 1.FE.6 | Cerradas como MVP RF-07/RF-08 (dos leyendas; detalle con día/zona = Sin asignar). No exigir datos reales planned/completed ni RBAC de campo |
| T.DOC.3 | Manual por rol; **después** de fases 1–4. No sustituye este estudio |
| 5.QA.3 | Formación piloto de despliegue; distinta de usabilidad de MVP |

---

**Cierre:** publicar este protocolo no cambia el checkbox de 1.FE.8. El siguiente entregable es el informe de la sección 12, escrito **tras** sesiones con personas del perfil de la sección 2.
