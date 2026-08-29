# Documento de Requisitos — Aplicación de Optimización de Rutas para Visitas a Pacientes

## 1. Información general

| Campo | Valor |
|---|---|
| Nombre del proyecto | App de Planificación y Optimización de Rutas de Visitas Domiciliarias |
| Versión del documento | 1.0 |
| Fecha | 2026-08-29 |
| Estado | Borrador para revisión |

## 2. Objetivo

Desarrollar una aplicación que, a partir de un listado de direcciones proporcionado en un documento Excel, permita:

1. Geolocalizar y visualizar en un mapa un conjunto de direcciones (pacientes).
2. Organizar y agrupar dichas direcciones por zonas geográficas para su gestión mensual.
3. Optimizar los desplazamientos diarios dentro de cada zona, sugiriendo la mejor ruta en función de tiempo y coste.
4. Generar mapas de rutas diarias por zona, almacenarlos como histórico y permitir compartirlos entre varios usuarios.

## 3. Contexto y problema a resolver

Los usuarios (gestores de visitas / personal sociosanitario) reciben mensualmente un listado de aproximadamente **200 pacientes** con sus direcciones, que deben ser visitados a lo largo de un mes. Actualmente la planificación de las visitas y la organización por zonas se realiza de forma manual, lo que genera:

- Rutas poco eficientes en tiempo y kilometraje.
- Dificultad para agrupar visitas por proximidad geográfica.
- Falta de trazabilidad de las rutas planificadas y ejecutadas (histórico).
- Dificultad para compartir la planificación entre distintos usuarios/equipos.

## 4. Alcance

### 4.1 Incluido en el alcance

- Importación de direcciones desde ficheros Excel (.xlsx/.xls) y/o CSV.
- Geocodificación de direcciones (dirección → coordenadas).
- Visualización de las direcciones en un mapa interactivo.
- Agrupación automática/manual de direcciones en zonas.
- Distribución de las ~200 direcciones en un calendario mensual de visitas diarias.
- Cálculo de rutas óptimas diarias por zona (optimización de tiempo y coste).
- Generación de mapas de ruta diaria (uno por zona/día/usuario).
- Almacenamiento histórico de los mapas y rutas generadas.
- Compartición de mapas/rutas entre varios usuarios con control de acceso.
- Dataset ficticio de direcciones de la provincia de Bizkaia (incluyendo zonas rurales) para pruebas y demo.

### 4.2 Fuera de alcance (versión inicial)

- Navegación GPS turn-by-turn en tiempo real dentro de la app (se podrá exportar a apps de navegación externas: Google Maps, Waze, etc.).
- Facturación o gestión clínica de los pacientes.
- Integración con sistemas de historia clínica electrónica (podrá considerarse en fases futuras).
- Reoptimización dinámica en tiempo real ante imprevistos (tráfico en vivo), salvo como mejora futura.

## 5. Actores / Roles de usuario

| Rol | Descripción |
|---|---|
| **Administrador** | Gestiona usuarios, permisos, carga de ficheros maestros, configuración de zonas y parámetros de optimización. |
| **Planificador / Coordinador** | Importa el Excel mensual, define/ajusta zonas, genera y valida las rutas mensuales y diarias. |
| **Usuario de campo (visitador)** | Consulta su ruta diaria asignada, visualiza el mapa, marca visitas completadas. |
| **Supervisor / Responsable de equipo** | Consulta el histórico de rutas, comparte mapas con otros usuarios, analiza indicadores (KPIs) de tiempo/coste. |

## 6. Requisitos funcionales

### 6.1 Importación de datos

- **RF-01**: El sistema debe permitir subir un fichero Excel (.xlsx) con el listado de pacientes, incluyendo al menos: identificador del paciente, nombre (o referencia anonimizada), dirección, código postal, municipio y provincia.
- **RF-02**: El sistema debe validar el formato del fichero y reportar filas con errores (direcciones incompletas, códigos postales inválidos, duplicados).
- **RF-03**: El sistema debe permitir corregir manualmente direcciones que no se puedan geocodificar automáticamente.
- **RF-04**: El sistema debe soportar la carga de hasta al menos 500 registros por fichero, cubriendo el caso de uso de 200 pacientes/mes con margen de crecimiento.

### 6.2 Geolocalización y visualización en mapa

- **RF-05**: El sistema debe geocodificar automáticamente cada dirección importada (dirección textual → latitud/longitud).
- **RF-06**: El sistema debe mostrar todas las direcciones geolocalizadas sobre un mapa interactivo (zoom, desplazamiento, capas).
- **RF-07**: El mapa debe permitir distinguir visualmente las zonas (por color/icono) y el estado de cada visita (pendiente, planificada, completada).
- **RF-08**: El sistema debe permitir ver el detalle de cada punto (paciente, dirección, día/zona asignada) al seleccionarlo en el mapa.

### 6.3 Zonificación

- **RF-09**: El sistema debe permitir agrupar automáticamente las direcciones en zonas geográficas (p. ej. por clustering geográfico y/o por código postal/municipio).
- **RF-10**: El sistema debe permitir al planificador editar manualmente la asignación de una dirección a una zona.
- **RF-11**: El sistema debe permitir definir el número de zonas o el tamaño máximo de pacientes por zona/día en función de la capacidad del equipo.
- **RF-12**: El sistema debe considerar zonas rurales y urbanas de forma diferenciada, dado que la densidad de direcciones y los tiempos de desplazamiento varían significativamente.

### 6.4 Planificación mensual y diaria

- **RF-13**: El sistema debe distribuir las ~200 visitas mensuales en un calendario de visitas diarias, respetando restricciones configurables (días laborables, nº máximo de visitas/día, duración media de visita).
- **RF-14**: El sistema debe permitir reasignar o mover manualmente una visita de un día/zona a otro.
- **RF-15**: El sistema debe permitir asignar cada ruta diaria a un usuario de campo concreto.

### 6.5 Optimización de rutas

- **RF-16**: El sistema debe calcular, para cada ruta diaria por zona, el orden óptimo de visitas minimizando tiempo total de desplazamiento.
- **RF-17**: El sistema debe permitir un modo alternativo de optimización orientado a minimizar coste (p. ej. combustible/kilometraje) en lugar de tiempo.
- **RF-18**: El sistema debe mostrar al usuario una comparativa (tiempo estimado, distancia estimada, coste estimado) entre la ruta sugerida y una ruta no optimizada (orden original), para evidenciar el ahorro.
- **RF-19**: El sistema debe soportar restricciones básicas de ruta: punto de origen (p. ej. oficina/domicilio del usuario), punto de retorno, y franjas horarias si el paciente las requiere.
- **RF-20**: El sistema debe permitir recalcular la ruta si se añaden, eliminan o modifican direcciones de una zona/día.

### 6.6 Generación y gestión de mapas

- **RF-21**: El sistema debe generar un mapa visual de la ruta diaria optimizada por zona, con el orden de paradas numerado.
- **RF-22**: El sistema debe permitir exportar el mapa/ruta (imagen, PDF y/o enlace a Google Maps u otra app de navegación).

### 6.7 Histórico

- **RF-23**: El sistema debe almacenar de forma histórica cada mapa/ruta generado, con fecha, zona, usuario asignado y listado de direcciones/orden de visita.
- **RF-24**: El sistema debe permitir consultar el histórico filtrando por fecha, zona, usuario o paciente.
- **RF-25**: El sistema debe registrar el estado real de ejecución de la ruta (visitas completadas/no completadas) si el usuario de campo lo reporta, para comparar planificado vs. ejecutado.
- **RF-26**: El histórico debe conservarse al menos durante 12 meses (configurable), cumpliendo la normativa de protección de datos aplicable.

### 6.8 Compartición y colaboración

- **RF-27**: El sistema debe permitir compartir un mapa/ruta con uno o varios usuarios del sistema, con permisos de solo lectura o edición.
- **RF-28**: El sistema debe permitir compartir un mapa mediante enlace (con o sin caducidad) para usuarios externos, respetando la confidencialidad de los datos de pacientes.
- **RF-29**: El sistema debe notificar a los usuarios cuando se les comparte o reasigna una ruta.
- **RF-30**: El sistema debe llevar un control de auditoría (quién ha visto/editado/compartido cada ruta).

## 7. Requisitos no funcionales

| ID | Categoría | Requisito |
|---|---|---|
| RNF-01 | Rendimiento | El sistema debe geocodificar un lote de 200 direcciones en menos de 5 minutos. |
| RNF-02 | Rendimiento | El cálculo de optimización de una ruta diaria (hasta 20-25 paradas) debe completarse en menos de 15 segundos. |
| RNF-03 | Escalabilidad | El sistema debe soportar múltiples cargas mensuales concurrentes (varios equipos/zonas) sin degradación relevante. |
| RNF-04 | Disponibilidad | El sistema debe tener una disponibilidad objetivo del 99% en horario laboral. |
| RNF-05 | Seguridad | Los datos de pacientes (direcciones, identificadores) deben cifrarse en tránsito (HTTPS) y en reposo. |
| RNF-06 | Privacidad / RGPD | El sistema debe cumplir el RGPD y la LOPDGDD (datos de salud/pacientes como categoría especial de datos), incluyendo minimización de datos, control de acceso por rol y trazabilidad. |
| RNF-07 | Usabilidad | La interfaz de mapa y planificación debe ser utilizable por usuarios no técnicos, con formación mínima. |
| RNF-08 | Compatibilidad | La aplicación debe ser accesible desde navegador web (desktop) y adaptarse a dispositivos móviles/tablet para el usuario de campo. |
| RNF-09 | Interoperabilidad | El formato de importación debe soportar Excel (.xlsx/.xls) y CSV como mínimo. |
| RNF-10 | Mantenibilidad | El proveedor/servicio de mapas y geocodificación debe ser configurable (p. ej. Google Maps, OpenStreetMap/OSRM, Mapbox) para evitar dependencia de un único proveedor. |
| RNF-11 | Auditabilidad | Todas las acciones de compartición, edición y borrado de rutas deben quedar registradas con usuario y fecha/hora. |

## 8. Historias de usuario (ejemplos)

1. **Como planificador**, quiero subir el Excel mensual de 200 pacientes para que el sistema geolocalice automáticamente sus direcciones y las agrupe por zonas.
2. **Como planificador**, quiero ver en un mapa las zonas propuestas y poder mover manualmente un paciente de una zona a otra antes de confirmar la planificación mensual.
3. **Como planificador**, quiero que el sistema me sugiera la ruta diaria óptima por zona (en tiempo y coste) para reducir los desplazamientos del equipo.
4. **Como usuario de campo**, quiero consultar en el móvil el mapa de mi ruta del día, con el orden de visitas, para no perder tiempo decidiendo el recorrido.
5. **Como supervisor**, quiero acceder al histórico de rutas de los últimos meses para analizar el cumplimiento y el coste real frente al planificado.
6. **Como supervisor**, quiero compartir el mapa de una ruta con otro compañero que cubrirá una baja, sin tener que volver a planificar desde cero.

## 9. Criterios de aceptación (resumen)

- El sistema geocodifica correctamente al menos el 95% de las direcciones de un fichero Excel bien formateado.
- El sistema agrupa las direcciones en zonas coherentes geográficamente (validación visual sobre el mapa).
- Para una zona de hasta 20 paradas, la ruta sugerida reduce el tiempo/distancia total frente a un orden aleatorio o alfabético en al menos un 15-20% (valor de referencia a validar en pruebas).
- Todo mapa generado queda accesible en el histórico inmediatamente después de su creación.
- Un usuario con permiso de "compartido" puede visualizar el mapa sin poder modificarlo; un usuario con permiso de "edición" sí puede modificarlo.

## 10. Restricciones y supuestos

- Se asume que las direcciones de los pacientes se proporcionan en formato de texto (calle, número, código postal, municipio); no se garantiza precisión si la dirección está incompleta o es ambigua.
- El cálculo de "coste" en la optimización se basará en una estimación (distancia × coste/km configurable + tiempo), no en datos de tráfico en tiempo real en la versión inicial.
- El tratamiento de datos de pacientes debe ajustarse a la normativa de protección de datos de salud vigente (RGPD/LOPDGDD); se recomienda anonimizar o seudonimizar el identificador del paciente en el fichero de origen cuando sea posible.
- Zonas rurales de Bizkaia pueden tener menor densidad de direcciones geocodificables automáticamente y mayores tiempos de desplazamiento; el sistema debe permitir ajuste manual en estos casos.

## 11. Glosario

- **Zona**: Agrupación geográfica de direcciones/pacientes, utilizada para organizar las visitas diarias.
- **Ruta óptima**: Secuencia de visitas dentro de una zona/día que minimiza el tiempo o el coste total de desplazamiento.
- **Histórico de mapas**: Repositorio de mapas/rutas generados en el pasado, consultables por fecha, zona o usuario.
- **Geocodificación**: Proceso de convertir una dirección textual en coordenadas geográficas (latitud/longitud).

## 12. Anexo — Dataset ficticio de direcciones (Bizkaia)

Se ha generado un listado ficticio de direcciones de ejemplo de la provincia de Bizkaia, incluyendo tanto zonas urbanas (Bilbao, Barakaldo, Getxo, etc.) como zonas rurales (Karrantza, Orduña, Arratzu, etc.), con sus respectivos códigos postales, para su uso en pruebas de geocodificación, zonificación y optimización de rutas.

Ver fichero adjunto: [`direcciones-ejemplo-bizkaia.csv`](./direcciones-ejemplo-bizkaia.csv)

> Nota: Todos los nombres, direcciones y datos de pacientes de este dataset son **ficticios** y se han generado únicamente con fines de demostración y prueba. El fichero se entrega en formato CSV (delimitado por punto y coma) para facilitar su apertura directa en Excel; para la aplicación real se recomienda cargarlo como .xlsx.
