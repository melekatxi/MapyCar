# Verdad de referencia de geocodificación (0.QA.2)

> **Estado: APROBADO manualmente el 2026-08-29** por el responsable del proyecto, tras
> revisión fila por fila (30/30) contra la instancia Nominatim autoalojada.
> **Enmienda 2026-08-30 (opción 1)**: 4 portales del fixture no existían en el callejero
> oficial Eustat y se sustituyen por portales oficiales verificados (ver tabla de
> enmienda más abajo). El 24/30 (80%) del 29 era first-hit de Nominatim **sin scorer**
> y no es comparable con RF-05. Matching RF-05 (scorer + overlay, Nominatim local
> 2026-08-30): **28/28 (100%)** en direcciones bien formateadas — ver
> [`scripts/qa/geocoding-benchmark.md`](../../scripts/qa/geocoding-benchmark.md).
> Durante la revisión del 29 se corrigieron 2 códigos postales del fixture que no
> coincidían con el CP real de ese tramo (PAC-005: 48005→48006, PAC-012: 48001→48009).
> La consulta usa calle+número normalizados (sin piso/puerta), igual que hará
> el worker de geocodificación (1.BE.8); el piso/puerta original se conserva
> en la columna Dirección para referencia.
>
> PAC-051 y PAC-058 siguen siendo rurales **intencionadamente ficticias** (caso
> negativo); no forman parte del denominador de 28 direcciones bien formateadas.

| ID | Dirección | CP | Municipio | Tipo | Lat (borrador) | Lon (borrador) | Resultado Nominatim |
|---|---|---|---|---|---|---|---|
| PAC-001 | Calle Ledesma 12, 3º Izq | 48001 | Bilbao | Urbana | 43.2622764 | -2.9285954 | FINO, 12, Ledesma kalea, Abando, Bilbao, Bizkaia, Euskadi, 48001, España |
| PAC-002 | Gran Vía Don Diego López de Haro 45, 1º | 48011 | Bilbao | Urbana | 43.2633127 | -2.9375174 | Casa Ramón de la Sota, 45, On Diego Lopez Haroko kale nagusia, Abandoibarra, Indautxu, Abando, Bilbao, Bizkaia, Euskadi, 48011, España |
| PAC-003 | Calle Autonomía 8, 2º Dcha | 48012 | Bilbao | Urbana | 43.2575092 | -2.9361231 | 8, Autonomia kalea, Autonomia, Indautxu, Abando, Bilbao, Bizkaia, Euskadi, 48012, España |
| PAC-004 | Calle Zabalbide 92, Bajo | 48006 | Bilbao | Urbana | 43.2585096 | -2.9103596 | 92, Zabalbide kalea, Txurdinaga, Otxarkoaga-Txurdinaga, Bilbao, Bizkaia, Euskadi, 48006, España |
| PAC-005 | Calle Iturribide 54, 4º | 48006 | Bilbao | Urbana | 43.2571202 | -2.9179199 | 54, Iturribide kalea, Iturralde, Ibaiondo, Bilbao, Bizkaia, Euskadi, 48006, España |
| PAC-006 | Avenida Sabino Arana 20, 3º | 48013 | Bilbao | Urbana | 43.262118 | -2.9470313 | 20, Sabino Arana etorbidea, Basurtu, Basurtu-Zorrotza, Bilbao, Bizkaia, Euskadi, 48013, España |
| PAC-007 | Calle Rekalde 33, 2º Izq | 48009 | Bilbao | Urbana | — | — | NOT_FOUND |
| PAC-008 | Calle Mazarredo 15, Ático | 48009 | Bilbao | Urbana | — | — | NOT_FOUND |
| PAC-009 | Calle Máximo Aguirre 10, 5º | 48011 | Bilbao | Urbana | 43.2642931 | -2.9375763 | 10, Maximo Aguirre kalea, Autonomia, Indautxu, Abando, Bilbao, Bizkaia, Euskadi, 48011, España |
| PAC-010 | Avenida Kirikiño 2, Bajo | 48012 | Bilbao | Urbana | 43.2555098 | -2.9354577 | 2, Kirikiño etorbidea, Iralabarri, Errekalde, Bilbao, Bizkaia, Euskadi, 48012, España |
| PAC-011 | Avenida de Zumalakarregi 40, 2º | 48007 | Bilbao | Urbana | — | — | NOT_FOUND |
| PAC-012 | Calle Colón de Larreategui 22, 3º | 48009 | Bilbao | Urbana | 43.2634875 | -2.9318063 | 22, Kolon Larreategi kalea, Abando, Bilbao, Bizkaia, Euskadi, 48009, España |
| PAC-013 | Calle Iparragirre 60, 4º Dcha | 48010 | Bilbao | Urbana | 43.2606357 | -2.9375006 | Iparraguirre kalea, Autonomia, Indautxu, Abando, Bilbao, Bizkaia, Euskadi, 48010, España |
| PAC-014 | Calle Elcano 18, 1º | 48008 | Bilbao | Urbana | 43.2605669 | -2.9337268 | 18, Elcano kalea, Abando, Bilbao, Bizkaia, Euskadi, 48008, España |
| PAC-015 | Calle Uribitarte 6, 2º | 48001 | Bilbao | Urbana | 43.2641543 | -2.9273408 | Irontec, Internet y Sistemas sobre GNU/Linux, 6, Uribitarte kalea, Uribitarte, Abando, Bilbao, Bizkaia, Euskadi, 48001, España |
| PAC-034 | Galbarriatu | 48160 | Zamudio | Rural | 43.2820604 | -2.8979386 | Galbarriatu, Zamudio, Bizkaia, Euskadi, 48160, España |
| PAC-037 | Barrio Bengoetxe 5 | 48960 | Galdakao | Rural | 43.232828 | -2.860011 | overlay Eustat: Bengoetxe (Auzoa/Barrio) 5 48960 (Nominatim local no trae `addr:housenumber` 5) |
| PAC-043 | Aldebaraieta | 48212 | Mañaria | Rural | 43.1428869 | -2.6693791 | Aldebaraieta, Mañaria, Bizkaia, Euskadi, 48212, España |
| PAC-044 | Berrio | 48230 | Elorrio | Rural | 43.1384633 | -2.5239265 | Berrio, Elorrio, Bizkaia, Euskadi, 48230, España |
| PAC-045 | Besoita | 48240 | Berriz | Rural | 43.1900183 | -2.5740427 | Besoita, Berriz, Bizkaia, Euskadi, 48240, España |
| PAC-046 | Sallabente | 48260 | Zaldibar | Rural | 43.1784582 | -2.4943544 | Sallabente, Zaldibar, Bizkaia, Euskadi, 48260, España |
| PAC-047 | Santa Apolonia | 48215 | Iurreta | Rural | 43.1757166 | -2.6515574 | Santa Apolonia, Arriandi, Iurreta, Bizkaia, Euskadi, 48215, España |
| PAC-048 | Irazola Auzoa | 48291 | Abadiño | Rural | 43.1290754 | -2.604474 | Irazola auzoa, Abadiño, Bizkaia, Euskadi, 48291, España |
| PAC-051 | Barrio Errigoiti Auzoa 3 | 48311 | Errigoiti | Rural | — | — | NOT_FOUND |
| PAC-052 | Luparia | 48392 | Muxika | Rural | 43.2888753 | -2.6847392 | Luparia, Muxika, Bizkaia, Euskadi, España |
| PAC-053 | Zubiate | 48383 | Arratzu | Rural | 43.3087689 | -2.6438744 | Zubiate, Arratzu, Bizkaia, Euskadi, 48383, España |
| PAC-054 | Gabika | 48313 | Ereño | Rural | 43.3393654 | -2.6000851 | Gabika, Ereño, Bizkaia, Euskadi, 48313, España |
| PAC-055 | Allika | 48311 | Ibarrangelu | Rural | 43.395487 | -2.653907 | Allika, Ibarrangelu, Bizkaia, Euskadi, 48311, España |
| PAC-058 | Barrio Kortezubi Auzoa 3 | 48315 | Kortezubi | Rural | — | — | NOT_FOUND |
| PAC-060 | Abaroa | 48395 | Sukarrieta | Rural | 43.3926231 | -2.7026606 | Abaroa, Sukarrieta, Bizkaia, Euskadi, 48395, España |

## Enmienda 2026-08-30 — 4 portales inexistentes (opción 1)

Decisión de producto: **no** excluir las 4 filas del denominador de RF-05 y **no**
inventar números. Se sustituyen por el portal oficial más cercano en la misma vía
(Eustat CC-BY 4.0, cruzado con Cartociudad y Nominatim local 2026-08-30).

| ID | Antes (inválido) | Después (oficial) | Fuente | Por qué este número |
|---|---|---|---|---|
| PAC-004 | Calle Zabalbide **90**, 48006 Bilbao | Calle Zabalbide **92**, 48006 Bilbao | Eustat `Zabalbide (Kalea/Calle), 92` 48006 (43.258382, −2.910736). Cartociudad `16.PV.MUN_480200149601`. Nominatim local: `place=house` 92. | Eustat salta 82→92; no hay 90. El 92 es el siguiente portal oficial y OSM ya lo tiene. |
| PAC-005 | Calle Iturribide **55**, 48006 Bilbao | Calle Iturribide **54**, 48006 Bilbao | Eustat `Iturribide (Kalea/Calle), 54` 48006 (43.257124, −2.917940). Cartociudad `16.PV.MUN_480200143375`. Nominatim local: `place=house` 54. | Eustat tiene 53, 54, 56; no hay 55. Se elige 54 (Cartociudad `find` del 55 devolvía el 54). El 56 también geocodifica `matched`; no se usa. |
| PAC-010 | Calle Kirikiño **3**, **48004** Bilbao | Avenida Kirikiño **2**, **48012** Bilbao | Eustat `Kirikiño (Etorbidea/Avenida), 2` 48012 (43.255468, −2.935475). Cartociudad `16.PV.MUN_480200144040`. Nominatim local: `place=house` 2 **solo** con «Avenida» (0 candidatos con «Calle»). | No hay Kirikiño en 48004 ni portal 3. Vía oficial = avenida en 48012, números 1, 2, 4… Se elige 2 (par más cercano al 3). El 4 también geocodifica `matched`. |
| PAC-037 | Barrio Bengoetxe **4**, 48960 Galdakao | Barrio Bengoetxe **5**, 48960 Galdakao | Eustat `Bengoetxe (Auzoa/Barrio), 5` 48960 (43.232828, −2.860011). Cartociudad `16.PV.MUN_480360160272` (caserío Txankanoena). Nominatim local: tramos de `Bengoetxe auzoa` **sin** `addr:housenumber` 5. | El barrio oficial empieza en el 5. Overlay local sembrado con ese portal Eustat (no se sube a OSM.org). |

Las coordenadas de la tabla principal para estas 4 filas son evidencia del geocodificador
(Nominatim para las 3 urbanas; overlay Eustat para PAC-037), no se han insertado como
respuesta circular en el matcher. El overlay **no** contiene 90/55/3/4.
