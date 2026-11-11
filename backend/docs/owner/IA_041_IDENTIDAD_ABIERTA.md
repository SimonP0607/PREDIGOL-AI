# IA-041 — Identidad abierta de jugadores: Wikidata y Reep

*Plan Maestro de Evolución de PrediGol Intelligence 2026, pieza INT-B03, ola 1. Medido el 11-nov-2026.*

Investigación de solo lectura. No se escribió en la base de datos, no se hizo ninguna llamada a API-Football y no se contrató nada.

## Qué se midió

**Pregunta.** ¿Qué parte de los jugadores de las plantillas actuales de las competiciones prioritarias se puede enlazar, con su id de API-Football, a una identidad abierta y estable (Reep, Wikidata) que aporte alias de nombre? ¿Con qué precisión?

**Universo.** Plantillas actuales de PrediGol: `core.squad_members` con `last_seen_at = core.teams.squad_checked_at`, de los equipos con partidos en la temporada actual. Las plantillas se leyeron entre el 4-oct y el 9-nov-2026. El perfil sale de `core.players`.

| Competición | Equipos (temporada actual) | Jugadores |
| --- | ---: | ---: |
| Champions League: todos / fase de liga | 81 / 36 | 2.503 / 1.136 |
| Premier League | 20 | 629 |
| LaLiga | 20 | 655 |
| Serie A | 20 | 628 |
| Bundesliga | 18 | 523 |
| Ligue 1 | 18 | 510 |
| Libertadores: todos / fase de grupos | 47 / 32 | 1.564 / 1.080 |
| Sudamericana: todos / fase de grupos | 56 / 32 | 1.861 / 1.091 |
| **Total (distintos)** | **246** | **7.800** |

No había eliminatorias que medir. Las clasificaciones al Mundial que sigue PrediGol (ids 29–34 y 37) no tienen partidos en los últimos 45 días ni en los próximos 60. La última fecha en la base es el 1-abr-2026.

**Qué es Reep.** Es un registro de identidades del fútbol (withqwerty, github.com/withqwerty/reep): personas, equipos y competiciones, cada una con un id propio y los ids que tiene en otros proveedores. Hay dos versiones:

| | Reep v0 (repositorio GitHub) | Reep v1 (reep.football) |
| --- | --- | --- |
| Estado | Congelado. Último CSV `2026.25`, generado el 21-jun-2026. Sin correcciones posteriores. | Vivo. La descarga vigente es la release `2026-10-19.1`: exportada el 19-oct, republicada el 22-oct y activada el 5-nov-2026. |
| Formato | CSV planos: `people.csv` (444.707 filas, una columna `key_*` por proveedor), `teams.csv` (45.337). | Parquet, CSV.gz y DuckDB: `entities`, `bridges` (reep_id, provider, namespace, external_id…), `redirects`, `overlay_links` (QID de Wikidata), `overlay_aliases`, `provider_aliases`. |
| API-Football | `key_api_football` en 36.177 personas y en solo 10 equipos. Hay 19 ids asignados a más de una persona: el 306 apunta a Mohamed Salah y también a un homónimo nacido en 1983. | Proveedor *bridge-only* (sus ids se enlazan, pero no cuentan como evidencia independiente). Tiene 734.358 puentes, de ellos 155.518 de jugadores y 16.232 de equipos. |
| Tamaño | 444.707 personas, alrededor de 45 columnas de proveedor. | 442.284 jugadores, 25.856 entrenadores y 25.991 equipos, con puentes de 33 proveedores. |
| Fecha de nacimiento | Sí, tomada de Wikidata. | No: los 442.284 jugadores figuran como `redacted_private`. Retiene además a 9.116 menores conocidos. |
| Calidad declarada | — | Según su manifiesto: precisión del 99,53 %, *recall* del 96,81 % y puerta superada. No está verificado por nosotros. |

**Wikidata.** No hay ninguna propiedad para el id de API-Football: la búsqueda SPARQL de «api-football», «api football» y «api-sports» en las etiquetas de todas las propiedades no devolvió nada. El puente con Wikidata es, por tanto, API-Football → Reep v1 → QID, que Reep enlaza sobre todo mediante Transfermarkt (P2446, *Transfermarkt player ID*) y FBref (P5750), con un control de fecha de nacimiento. Además, Reep da el id de Transfermarkt del 99,8 % de los jugadores cruzados.

**Vías de cruce, en orden.**
1. Id exacto en Reep v1. Es la vía principal.
2. Id exacto en Reep v0.
3. Nombre normalizado más fecha de nacimiento contra Reep v0, solo para jugadores con fecha y todavía sin QID, y solo si hay un único candidato.
4. Puente Transfermarkt o QID hacia la entidad v1 de los jugadores que llegaron por la vía 3.

## Resultados

### 1. Cobertura por competición (todas las plantillas)

Son porcentajes sobre todos los jugadores de la plantilla. «Identidad abierta» significa una entidad de Reep o un QID por cualquier vía.

| Competición | n | Con fecha de nacimiento en PrediGol | Reep v1, id exacto | Identidad abierta | QID de Wikidata |
| --- | ---: | ---: | ---: | ---: | ---: |
| Champions (81 equipos) | 2.503 | 2.134 (85,3 %) | 1.905 (76,1 %) | 2.082 (83,2 %) | 1.908 (76,2 %) |
| Champions, fase de liga (36) | 1.136 | 1.006 (88,6 %) | 906 (79,8 %) | 987 (86,9 %) | 966 (85,0 %) |
| Premier League | 629 | 585 (93,0 %) | 558 (88,7 %) | 587 (93,3 %) | 562 (89,3 %) |
| LaLiga | 655 | 566 (86,4 %) | 520 (79,4 %) | 557 (85,0 %) | 533 (81,4 %) |
| Serie A | 628 | 566 (90,1 %) | 526 (83,8 %) | 563 (89,6 %) | 547 (87,1 %) |
| Bundesliga | 523 | 476 (91,0 %) | 438 (83,7 %) | 468 (89,5 %) | 464 (88,7 %) |
| Ligue 1 | 510 | 449 (88,0 %) | 375 (73,5 %) | 441 (86,5 %) | 437 (85,7 %) |
| Libertadores (47) | 1.564 | 1.267 (81,0 %) | 1.143 (73,1 %) | 1.222 (78,1 %) | 1.079 (69,0 %) |
| Libertadores, grupos (32) | 1.080 | 882 (81,7 %) | 793 (73,4 %) | 851 (78,8 %) | 771 (71,4 %) |
| Sudamericana (56) | 1.861 | 1.445 (77,6 %) | 1.285 (69,0 %) | 1.382 (74,3 %) | 1.137 (61,1 %) |
| Sudamericana, grupos (32) | 1.091 | 876 (80,3 %) | 775 (71,0 %) | 840 (77,0 %) | 697 (63,9 %) |
| Europa (6 competiciones, distintos) | 4.771 | 4.173 (87,5 %) | 3.759 (78,8 %) | 4.094 (85,8 %) | 3.856 (80,8 %) |
| CONMEBOL (2, distintos) | 3.029 | 2.398 (79,2 %) | 2.147 (70,9 %) | 2.300 (75,9 %) | 1.939 (64,0 %) |
| **Total (distintos)** | **7.800** | **6.571 (84,2 %)** | **5.906 (75,7 %)** | **6.394 (82,0 %)** | **5.795 (74,3 %)** |

En este universo, el id exacto no dio ningún conflicto en v1 (ningún id de API-Football apunta a dos entidades). Las vías 2 a 4 añaden 488 identidades a las 5.906 de la vía 1. La vía 3 identifica a 150 jugadores que no tenían id exacto; 116 de ellos con QID y 110 alcanzados también en v1. Otros 6 casos con dos o más candidatos se dejaron sin enlazar.

### 2. Dónde está la brecha

| Grupo (fecha de referencia: 11-nov-2026) | n | Reep v1, id exacto | Identidad abierta | QID |
| --- | ---: | ---: | ---: | ---: |
| Sin fila en `core.players` | 254 | 13 | 13 | 5 |
| Con fila pero sin fecha de nacimiento | 975 | 6 | 15 | 12 |
| Menores de 18 | 36 | 24 | 27 | 22 |
| Nacidos en 2005 o después (18 años o más) | 1.166 | 939 (80,5 %) | 1.063 (91,2 %) | 843 (72,3 %) |
| Nacidos antes de 2005 | 5.369 | 4.924 (91,7 %) | 5.276 (98,3 %) | 4.913 (91,5 %) |
| **Con fecha de nacimiento (los tres grupos anteriores)** | **6.571** | **5.887 (89,6 %)** | **6.366 (96,9 %)** | **5.778 (87,9 %)** |

Por competición, solo entre los jugadores con fecha de nacimiento:

| Competición | n | Reep v1, id exacto | Identidad abierta | QID | Sin perfil o sin fecha (fuera de la tabla) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Champions | 2.134 | 88,9 % | 97,1 % | 89,2 % | 369 |
| Champions, fase de liga | 1.006 | 90,0 % | 97,7 % | 95,7 % | 130 |
| Premier League | 585 | 94,2 % | 99,1 % | 95,6 % | 44 |
| LaLiga | 566 | 91,9 % | 97,7 % | 93,5 % | 89 |
| Serie A | 566 | 92,9 % | 99,1 % | 96,3 % | 62 |
| Bundesliga | 476 | 92,0 % | 98,1 % | 97,3 % | 47 |
| Ligue 1 | 449 | 83,5 % | 98,2 % | 97,3 % | 61 |
| Libertadores | 1.267 | 90,0 % | 96,1 % | 84,9 % | 297 |
| Sudamericana | 1.445 | 88,7 % | 95,4 % | 78,5 % | 416 |

Quedan sin cruzar 205 jugadores que sí tienen fecha de nacimiento. Se tomó una muestra de 20 y se buscó cada uno en Wikidata en vivo (futbolista, fecha exacta y apellido en la etiqueta): aparecieron 8. Siete de ellos tienen un QID posterior al más alto de v0 (Q138842827). Cinco de los 8 ya están en la capa Wikidata de Reep v1, pero sin el id de API-Football que usa PrediGol. Uno estaba en v0 con la etiqueta mal escrita («Daniel Mandriou»), y la regla de nombre lo descartó. Trece de los 20 nacieron en 2005 o después.

### 3. Precisión

**Vía 1 (id exacto en Reep v1, n = 5.906).**

*Muestra a mano de 30 cruces.* Se eligieron estratificados por competición (semilla 41) y se revisaron contra Wikidata en vivo el 11-nov-2026 (etiqueta, P569 con su precisión, P2446 y P54). En los 30 casos es la misma persona.
- 29 tienen ítem en Wikidata, y en los 29 el id de Transfermarkt coincide con el de Reep y el nombre es compatible.
- Fecha de nacimiento: es idéntica en 25 casos. En 1 Wikidata solo da el año, que coincide. En 3 difiere entre 2 y 5 días: Baldomero Perlaza, Juan Camilo «Cucho» Hernández y Lucas Veríssimo.
- El caso restante (G. Añasgo) no tiene QID en Reep ni ítem en Wikidata con su id de Transfermarkt, pero su nombre completo es idéntico en Reep y en API-Football.
- Con 30 de 30 aciertos, el límite inferior de Wilson al 95 % es del 88,6 %.

*Control automático sobre todo el conjunto.* Se comparó la fecha de PrediGol con la de Wikidata, tomada de la instantánea v0 a través del QID. La comparación fue posible en 5.213 jugadores:
- Fecha idéntica: 5.040 (96,7 %).
- Mismo año con otro día, o fecha solo con año: 151 (2,9 %).
- Año distinto: 22 (0,42 %).

Se revisaron contra Wikidata en vivo 14 de los 22 con año distinto. En 12, la fecha de PrediGol figura hoy en Wikidata: o había varias fechas o la instantánea v0 estaba desactualizada. Dos siguen en conflicto (K. Vázquez: 2001 en PrediGol y 2004 en Wikidata; M. Soula: 1998 y 1993), pero ninguno parece ser otra persona. La comprobación de nombres dio 3 avisos entre los 5.906, y los 3 resultaron falsos: son apellidos cortos que la regla ignora (Sy, Ba-Sy, Ta Bi).

**Vía 3 (nombre más fecha de nacimiento, n = 150).** De una muestra de 12, se confirmaron 10 en Wikidata en vivo. En los 10 coincide la fecha exacta; el nombre coincide en 9 (el décimo no tiene etiqueta en inglés) y el id de Transfermarkt en 8. Los otros 2 no se pueden verificar porque no tienen QID. No se encontró ningún error.

### 4. Nombres y alias: lo que aporta a INT-B04

Datos sobre los 5.906 cruces de la vía 1:

| Medida | Valor |
| --- | ---: |
| Nombre de API-Football abreviado (tipo «M. Salah») | 4.448 (75,3 %) |
| De esos, con nombre completo en Reep | 4.448 (100 %) |
| Con al menos un alias distinto de los nombres que guarda PrediGol | 5.898 (99,9 %); mediana de 4 alias extra |
| Con algún alias en escritura no latina (árabe, cirílico, CJK…) | 4.709 (79,7 %) |
| Con alias multilingües de Wikidata | 5.035 (85,3 %) |
| Con id de Transfermarkt; ids de proveedor por jugador | 5.893 (99,8 %); mediana de 19 (p10: 16) |
| Jugadores con algún campo de nombre mal codificado en PrediGol (de 7.800) | 22 (0,3 %), p. ej. «R. ObriÄ», que en Reep es «Relja Obrić» |
| Club actual de Wikidata (P54 sin fecha de fin) igual al club de PrediGol, en la muestra de 30 | 9 de 29 con ítem; 12 desactualizados; 8 sin dato |

### 5. Clubes: base de INT-B02

| Competición | Equipos | Puente API-Football → Reep | QID | Web oficial (P856) | Alguna red social |
| --- | ---: | ---: | ---: | ---: | ---: |
| Champions | 81 | 81 | 80 | 78 | 72 |
| Premier League | 20 | 20 | 19 | 19 | 19 |
| LaLiga | 20 | 20 | 20 | 20 | 20 |
| Serie A | 20 | 20 | 20 | 20 | 20 |
| Bundesliga | 18 | 18 | 18 | 17 | 17 |
| Ligue 1 | 18 | 18 | 18 | 18 | 17 |
| Libertadores | 47 | 47 | 36 | 31 | 32 |
| Sudamericana | 56 | 56 | 45 | 35 | 39 |
| **Distintos** | **246** | **246** | **229** | **212** | **210** |

Las redes sociales contadas son X (P2002), Instagram (P2003), Facebook (P2013), YouTube (P2397) y TikTok (P7085). Por región, de los QID: Europa tiene web en 151 de 154 y CONMEBOL en 61 de 75. Los clubes sin web en Wikidata son sobre todo de CONMEBOL, más FC Augsburg, KF Drita y Ararat-Armenia.

## Conclusiones

1. **Reep cubre la mayoría de las plantillas prioritarias, así que el gate de INT-B03 se cumple.** Por id exacto de API-Football enlaza 5.906 de 7.800 jugadores (75,7 %). Va del 69,0 % en la Sudamericana al 88,7 % en la Premier, y ninguna competición queda por debajo de la mitad. Entre los jugadores con perfil completo en PrediGol, cubre el 89,6 % por id exacto y el 96,9 % por cualquier vía abierta.
2. **El cruce por id exacto es fiable como identidad.** La muestra a mano dio 30 de 30, con 29 verificados de forma independiente en Wikidata por id de Transfermarkt, nombre y fecha. En el conjunto completo solo el 0,42 % difiere en el año de nacimiento, y casi siempre se explica por fechas múltiples o corregidas en Wikidata. No se encontró ningún caso de otra persona. Aun así, 30 casos solo garantizan un 88,6 % al 95 %: la cota del 95 % de G-FUENTES 3 tiene que medirse en INT-B04 sobre el enlace noticia → jugador.
3. **Wikidata solo se alcanza a través de Reep.** No tiene propiedad para API-Football, así que la cadena es API-Football → Reep → QID (vía Transfermarkt P2446 o FBref P5750). Con ella se obtiene QID para el 74,3 % de los jugadores (87,9 % con perfil) y para 229 de los 246 clubes. Wikidata es más débil en CONMEBOL: 64,0 % de jugadores con QID, frente al 80,8 % de Europa. Para INT-B02 da la web oficial de 212 clubes, aunque hay que verificarla contra el propio sitio.
4. **Para INT-B04, lo valioso son los nombres.** El 75 % de los jugadores cruzados tiene en API-Football un nombre abreviado («M. Salah»). Reep da el nombre completo en todos esos casos, una mediana de 4 alias extra y transliteraciones no latinas en el 80 %, que es justo lo que necesita una resolución en mundo cerrado contra las dos plantillas del partido. La clave tiene que seguir siendo `provider_player_id`; el alias solo debe proponer candidatos dentro de esas dos plantillas. Wikidata no sirve para saber el club actual (coincidió en 9 de 29), y menos aún la disponibilidad: es identidad, nunca estado.
5. **La brecha está en datos que faltan, no en errores, y exige refresco.** El 15,8 % de los jugadores de las plantillas no tiene perfil o fecha en PrediGol, y de ellos solo se identifican 28 de 1.229. Los nacidos desde 2005 quedan en el 91,2 % frente al 98,3 % del resto, y 7 de los 8 recuperables de la muestra tenían un QID posterior a la instantánea v0. Propuesta para el resultado de la ficha: una tabla de referencia aparte, con clave `provider_player_id` y las columnas reep_id, QID, id de Transfermarkt, nombre canónico, alias, vía, release de Reep y fecha. Se cargaría desde la descarga CC0 de Reep v1, fijando release y sha256, con refresco periódico, y sin tocar nunca los datos del proveedor.

## Limitaciones y licencias

- **Licencias, comprobadas en la fuente.** Reep v0 es CC0 1.0 (fichero `LICENSE` del repositorio; el README lo describe como derivado de Wikidata). Reep v1 es CC0 1.0 para toda la release, puentes incluidos. Pide que se cite, pero no lo exige, y advierte que el CC0 no da derechos sobre material de terceros. Los datos estructurados de Wikidata son CC0 (página `Wikidata:Licensing`). La API alojada de Reep se concede a petición, y el acceso de producción es de pago, pero no hace falta: basta la descarga.
- **Actualidad.** v0 está congelado desde el 21-jun-2026. La página de descargas de v1 anuncia la release `2026-10-25.1`, pero sus enlaces sirven la `2026-10-19.1`, y el manifiesto de la 10-25.1 marca `gate_passed: false`. El 22-oct Reep retiró de la release los ids de Football Manager. Por todo ello hay que fijar una release concreta y guardar su versión.
- **Sin fecha de nacimiento en v1, y menores retenidos.** Por eso el respaldo por nombre más fecha se apoyó en v0, que está congelado y arrastra errores comunitarios. Ejemplos: la etiqueta errónea «Yamil yamil» en el ítem de Lamine Yamal (Q113704154), ya corregida en Wikidata en vivo, y «Daniel Mandriou» en lugar de Mandroiu. La regla de nombre es estricta y pierde casos así; un respaldo contra Wikidata en vivo recuperaría más.
- **API-Football es *bridge-only* en Reep.** Hay jugadores que Reep tiene pero sin el id de API-Football que usa PrediGol (p. ej. A. Khusanov, que solo llegó por nombre más fecha y Transfermarkt). La causa posible, ids duplicados en API-Football o que Reep enlace otro id, no se midió.
- **Límites de la medición.** El control automático de fechas usa la instantánea v0 (jun-2026); Wikidata en vivo solo se consultó para las muestras. Las muestras son pequeñas (30, 12, 20 y 15), así que sus intervalos son anchos. El universo es el de las plantillas leídas entre el 4-oct y el 9-nov. No se midieron las cuentas sociales de jugadores, ni la ambigüedad de alias dentro de una plantilla, ni la precisión del enlace noticia → jugador, que corresponde a INT-B04.

## Cómo se midió

1. **Fuentes leídas el 10 y 11-nov-2026.** De Reep v0: README, `LICENSE` y `data/meta.json` en GitHub (commit `0ec59faa`). De Reep v1: las páginas `reep.football/downloads` y `/coverage`, y en `data.reep.football` los ficheros `releases/latest.json`, `release.json` y el manifiesto de las releases 2026-10-19.1 y 2026-10-25.1. De Wikidata: la página `Wikidata:Licensing`.
2. **Producción en solo lectura.** Se usó `psq`, es decir, psql con `default_transaction_read_only=on` y `statement_timeout` de 95 s; scripts `q1.sh`–`q4_dl_export.sh`. Las consultas tocaron `core.competitions`, `core.competition_seasons` (`is_current`), `core.fixtures` (equipos de la temporada y rondas de fase principal), `core.squad_members` cruzado con `core.teams.squad_checked_at` (plantilla actual) y `core.players`. El CSV mínimo (id, nombres, fecha de nacimiento, nacionalidad, equipo, competición) se quedó en el servidor, en `/tmp/lab_b03`.
3. **Descarga en el servidor**, dentro de `/tmp/lab_b03`. De Reep v1 (release 2026-10-19.1) se bajaron `bridges`, `entities`, `overlay_links`, `overlay_aliases`, `provider_aliases` y `redirects`, todos con sha256 verificado contra `release.json`. De Reep v0, `people.csv` y `teams.csv`.
4. **Cruce.** Se hizo con Python en la imagen `predigol-backend:5ae050a9c56a`, con `--network none`, `--cpus 1`, `--memory 3g` y montaje de solo lectura, sin base de datos; el script va dentro de `q6_run.sh` y `q11_run2.sh`. Duró unos 4 minutos. Se ejecutó dos veces y las tablas principales salieron idénticas.
   - Id exacto: `provider='api_football'`, `namespace='player'`, con las redirecciones resueltas y solo si hay una entidad única.
   - Normalización de nombres: sin tildes, en minúsculas, con tokens de 3 letras o más y sin partículas. Para dar un cruce por bueno se exige al menos un apellido en común.
   - Fecha abierta: la de v0 a través del QID.
5. **Wikidata, consultada con moderación.** Se hizo 1 búsqueda SPARQL de propiedades y 3 consultas SPARQL de verificación: las muestras (55 QID más 2 ids de Transfermarkt), los 20 no cruzados y los 229 clubes. Se leyeron además 2 páginas (P2446 y `Wikidata:Licensing`). Unas pocas llamadas a `wbsearchentities` recibieron 429 (límite compartido) y no se insistió.
6. **Muestras.** Hubo cuatro: 30 cruces exactos, estratificados por competición con semilla 41; 12 por nombre más fecha; 20 sin cruzar con fecha de nacimiento; y 15 con aviso. Todas se revisaron a mano contra Wikidata en vivo.
7. **Limpieza.** Se borró `/tmp/lab_b03` en el servidor (333 MB) y se borraron las copias locales de Reep. Los scripts de consulta y las consultas SPARQL son de trabajo y no forman parte del repositorio; esta sección describe lo que hacen.
