# IA-090 · Perfiles de club, selección, jugador y competición (C-09)

*Piezas AD-H07 (IA-090), AD-H05 (IA-091, bajas y sanciones) y AD-H06 (IA-092, convocatorias) del plan maestro de la arquitectura
definitiva 2026, olas 3 y 4. 17-nov-2026. Para la sesión de UX y para el dueño.*

Entrega a UX el contrato **C-09 · Perfiles** (versión `1.0.0`), registrado en el mecanismo de IA-057 con seis ejemplos. Solo lee
datos guardados: no llama a ningún proveedor, no añade migración, no crea interruptores y no cambia ninguna cifra, decisión,
pick, umbral, agente, prompt ni motor. No toca `decision-v1` ni `web/`.

## 1. Rutas (aditivas)

| Proyección | Ruta | Puerta |
| --- | --- | --- |
| Pública | `GET /api/v1/teams/{team_id}/profile` (club **o** selección: un solo recurso, `kind` dice cuál) | Las de hoy del producto + `FBI_PROFILES` (404 si está apagado) |
| Pública | `GET /api/v1/players/{player_id}/profile` | Igual |
| Pública | `GET /api/v1/competitions/{competition_id}/profile` | Igual |
| Privada | `GET /api/v1/admin/intelligence/teams/{team_id}/profile`, `…/players/{player_id}/profile`, `…/competitions/{competition_id}/profile` | `require_admin` (solo SUPER_ADMIN), sin interruptor |

`GET /teams/{id}`, `GET /players/{id}` y `GET /competitions/{id}` **no cambian de forma**: lo que UX ya construyó sigue igual.
La selección nacional no tiene ruta `/nations/{id}`: es el mismo recurso de equipo con `kind: "national_team"` y un bloque
`national` (lista, líderes de partidos y de goles).

**Aviso:** `FBI_PROFILES` está **encendido** en producción (`FBI_PROFILES=1` en `predigol-api`, leído en solo lectura el 17-nov a
las 04:27 UTC). En cuanto esto se despliegue, las tres rutas públicas responden a cualquier lector con sesión, aunque la web aún no
las llame. Solo sirven la proyección pública (datos guardados; ninguna previsión), pero UX debe saberlo.

## 2. Qué trae cada perfil

**Club y selección** (`team`): cabecera (escudo solo junto al nombre y si está guardado, decisión n.º 9; estadio con altitud si
AD-H04 la tiene; entrenador de la última alineación, AD-H03, con la fecha del partido), próximo partido, forma (5 últimos con
marcador), cifras de la temporada principal con local/visitante y, para cada cifra, en cuántos partidos hay dato
(`matches_with_data`), disponibilidad del próximo partido, plantilla (la última respuesta del proveedor), próximos partidos,
competiciones de la campaña con puesto y puntos, y palmarés **calculado** (abajo). Selección: además `national`.

**Jugador** (`player`): cabecera con **monograma** (nunca la foto del proveedor), disponibilidad, próximo partido **sin**
probabilidad de titularidad, 10 últimas apariciones, temporada por competición, **tasas por 90**, trayectoria, internacionalidades
y los trofeos que da el proveedor (rotulados como suyos).

**Competición** (`competition`): temporada, tabla, próximos partidos, goleadores, si su reglamento está codificado y la
cobertura de estadísticas (partidos terminados, con estadística de jugador y de equipo).

**Privada (sección «Intelligence»):** las selecciones en sombra de los partidos del equipo (14 días atrás, 7 adelante) con su
estado del ciclo, los ids externos (AD-H01) con las revisiones abiertas y, en el jugador, la lista de lo que añadirá el motor
(`not_yet_private`: titularidad AD-D04, previsiones AD-B08, mercados de jugador AD-E01). Nada de eso viaja en la pública, ni como
ausente.

Lo que aún no está (escenarios AD-B02, noticias AD-G07, palmarés externo AD-H01) viaja en `not_yet` con su pieza; cuando llegue
será un campo propio y una versión menor.

## 3. Reglas que cumple

1. **Tasas por 90 con su muestra.** Cuenta ÷ minutos × 90, solo con los partidos cuya planilla registra esa acción (un nulo no es
   un cero: una liga que no registra remates no baja los remates de nadie). Cada tasa lleva cuenta, partidos y minutos, y un
   intervalo del 95 % (intervalo de score de Poisson, la construcción de Wilson para un conteo). Por debajo de **450 minutos**:
   `muestra_insuficiente` con la muestra y el mínimo. Sin ningún partido con dato: `sin_datos` («sin estadística individual»),
   nunca 0. Ventana: 365 días. Paradas solo para porteros.
2. **No es el motor de jugadores.** Las tasas son lo que hizo, no una previsión: el servicio no importa `fbi.players` (lo prueban
   `test_people_per90.py` y `test_players_isolation.py`).
3. **Disponibilidad sin detalle médico (IA-091).** Cuatro estados (`disponible`, `duda`, `baja`, `sancionado`) con base, fuente y
   fecha. Bases, por precedencia: `oficial` (liga, federación o club), `proveedor` (parte de bajas de API-Football), `dos_origenes`,
   `un_medio`. Un rumor, un hecho contradicho o desactualizado no cambia nada. El motivo del proveedor se lee solo para separar
   sanción de lesión y se descarta; el texto de la prensa ni se selecciona. De la prensa solo cuentan los hechos de la investigación v1 (`fbi.ai.evidence.CONTEXT_SQL`): una afirmación de research v2, en sombra, nunca llega a un perfil, y esta pieza no añade ningún lector nuevo de `ai.evidence`. Si el parte de la temporada se pidió y no nombra a un
   jugador de la plantilla, está `disponible` (base `proveedor`, fecha de la consulta); si nunca se pidió, `sin_cobertura`: no
   saber no es «disponible». El código vive en `backend/src/fbi/people/availability.py` (no en `fbi/players/`, que es el motor en
   sombra y no puede servir a la API).
4. **Convocatorias (IA-092).** Una lista es `oficial` solo si viene del comunicado de la federación leído de una fuente que el
   registro autoriza (`verificada_autorizada`, firmada por el dueño, sin reserva de IA, acceso automatizado no restringido y
   autoridad `confirma` en convocatorias). Hoy **ninguna** fuente oficial lo cumple (directorio v2: de 671 oficiales, 559
   `verificada_pendiente_derechos`, 72 `bloqueada`, 40 `no_comprobada`; las 3 autorizadas son medios que solo «informan») y la
   ingesta de hechos oficiales (AD-C03) no está. Por eso la lista es la del **proveedor**, rotulada `level: "proveedor"`: los
   convocados del último partido con alineación (si tiene ≤ 120 días) o, si no, la plantilla del proveedor; y
   `official_state: "ninguna_fuente_oficial_autorizada"` con el número de fuentes permitidas (0). El recuento se recalcula con el
   registro en vigor en cada respuesta: el día que el dueño firme una fuente oficial, pasa a `sin_comunicado_ingerido`.
5. **Palmarés calculado** aparte del externo: un título de liga es ser primero en la **tabla final** de una temporada terminada,
   jugada como una sola tabla y sin otra fase (sin play-off ni final). Donde un play-off decide el campeón (Colombia, Argentina,
   México, MLS), el primero de la tabla no es campeón y no se cuenta. `since_season` dice desde cuándo hay datos.
6. **Bloques de una migración posterior** (altitud, ids externos, ciclo de selecciones) se leen en un punto de guardado: si la base
   no los tiene, el bloque dice `sin_datos` en lugar de romper la página.

## 4. Medido en producción (solo lectura, 17-nov-2026, 04:27–04:44 UTC)

| Qué | Resultado |
| --- | --- |
| Equipos con partido en 48 h en competiciones seguidas | 124 equipos (9 temporadas, ventana FIFA), 3.104 jugadores en plantilla |
| …cuya temporada tiene el parte de bajas pedido en 7 días | 124 de 124 (9 de 9 temporadas): estado con fuente y fecha para los 3.104 |
| Competiciones con parte del proveedor en 30 días | 17 |
| Selecciones (`core.team_kind`) con lista reciente (alineación o plantilla en 120 días) | 233 de 546 (42,7 %); de las 221 con nombre de absoluta, 217 (98,2 %) |
| Jugadores con ≥ 450 min en 365 días / con ≥ 450 min con remates registrados | 24.650 / 17.470 (70,9 %) |
| Tiempos (EXPLAIN ANALYZE): partidos de 330 días del club más activo · apariciones de 365 días del peor caso (id 0 del proveedor, que nunca es un jugador del perfil) · goleadores de una temporada · hechos de prensa de un partido | 4,9 ms · 298 ms · 119 ms · 1,5 ms |

La cobertura por confederación no se puede medir: `core.countries` no guarda la confederación.

## 5. Cómo se apaga o se revierte

- Para lectores: `FBI_PROFILES` apagado (o sin la línea) → las tres rutas públicas responden 404. Apaga también las páginas de UX.
- Para todos: revertir el PR. Son rutas y ficheros nuevos; no hay migración ni datos que deshacer.

## 6. Dónde está

| Qué | Fichero |
| --- | --- |
| Contrato | `backend/src/fbi/api/contracts/intelligence/profiles.py` (registrado en `registry.py`) |
| Servicio y SQL | `backend/src/fbi/api/services/profiles.py`, `backend/src/fbi/api/repositories/profiles.py` |
| Tasas por 90 | `backend/src/fbi/people/per90.py` |
| Disponibilidad (IA-091) | `backend/src/fbi/people/availability.py` |
| Convocatorias (IA-092) | `backend/src/fbi/people/call_ups.py` |
| Rutas | `backend/src/fbi/api/routers/football.py` (equipo, competición), `center.py` (jugador) |
| Ejemplos | `backend/tests/fixtures/contracts/intelligence/C-09/` |
| Pruebas | `tests/unit/test_profiles_contract.py`, `test_people_per90.py`, `test_people_availability.py`, `test_call_ups.py`; `tests/integration/test_profiles_c09.py` |
