# Etapas y cruces de cada competición (Plan Maestro, fase F2)

**Qué es.** Hasta hoy, «en qué parte de la competición está este partido» llegaba como texto libre del proveedor
(`Clausura - 12`, `Round of 16`, `Group Stage - 3`) y cuatro lugares lo leían cada uno con su propia expresión regular (las tablas
por etapa, el contexto de la IA, el dossier y la regla de sede neutral), así que podían discrepar sobre el mismo partido. Nada
decía que un partido es la vuelta de un cruce, cuánto iba el global ni quién pasó. F2 lo guarda una vez, con **un solo lector** de
las etiquetas de ronda y **un solo constructor de cruces**, y todo lo demás pregunta a la base de datos en vez de volver a leer
palabras. **No cambia ningún modelo, pronóstico, pick ni liquidación, ni el modo SHADOW.**

## Qué escribe (y qué no)

Migración **0082**, solo aditiva y reversible:

| Objeto | Para qué |
|---|---|
| `core.competition_stages` | Una fila por temporada y etapa (la ronda sin su número de jornada): fase, tipo (`league`/`knockout`/`qualifying`/`friendly`/`unresolved`), papel, ronda del cuadro (`final`, `round_of_16`…), cuántos partidos y cuándo, cómo se juegan sus cruces y con qué versión de las reglas se leyó. |
| `core.ties` | Una fila por cruce de una etapa eliminatoria: los dos lados, el formato (`single`, `two_legged`, `replay`, `series`), los partidos, el global, quién pasó y **cómo** (tiempo normal, prórroga, penales, global, gol de visitante, desempate, decisión administrativa, serie), la tanda de penales y si la ronda siguiente confirma al ganador. Un cruce que no se puede cerrar dice por qué (`reason`) en vez de adivinar. |
| `core.fixtures.stage_id / leg / tie_id` | Tres columnas nulas: etapa, cruce y partido (ida = 1, vuelta = 2). **Nulo = «aún no construido»: el sistema se comporta como antes.** |

Son tablas **derivadas** (como `core.fixture_venue_class`): el constructor las reescribe cuando cambian los hechos (un resultado
corregido, una ronda renombrada por el proveedor, una regla mejorada), por eso no son solo de añadir. Guardan el **resultado** de un
cruce, así que **nada que decida o juzgue un pick antes del partido puede leerlas**: los lectores previos al partido pasan por una
única puerta (`fbi.competitions.context`) que solo ve la estructura y los partidos del cruce con resultado registrado *a esa
hora*; un test envenena todas las columnas de resultado y exige que el paquete no cambie ni un byte, y otro impide que cualquier
otro módulo nombre estas tablas.

## Qué ve el producto ahora

* **Centro de partido** (`GET /api/v1/matches/{id}/center`, campos nuevos `stage` y `tie`): la etapa («Round of 16») y, si el
  partido es una pata de un cruce, el formato, cuál pata es, el global de las patas anteriores, el global al terminar, todas las
  patas con su marcador y la tanda de penales, y quién pasó. Todos los marcadores están contados **desde el local y el visitante de
  ese partido**. El veredicto (quién pasó y cómo) **solo aparece cuando el partido ya terminó**: la página de un partido que no ha
  terminado nunca lo lleva, aunque la fila guardada diga «decidido».
* **Cabecera del partido (web):** «Vuelta» junto a la competición y, debajo del marcador, «Ida 0–2» antes del partido, «Global 1–2»
  mientras se juega (la ida más los goles del partido hasta ahora) y, al final, «Global 4–2» y «Pasa Villarreal · por el global».
  Un partido único no dice nada de más (su marcador y su línea de penales ya lo cuentan). Español e inglés.
* **Tabla de la etapa:** la tabla completa que se abre bajo las dos filas ahora tiene **encabezados de columna** (#, Equipo, PJ, DG,
  Pts), igual que la de dos filas, y está nombrada para lectores de pantalla.
* **Paquete de la IA (`packet-v4`, aún no desplegado):**
  * bloque `phase`: la etapa y, para una vuelta, **solo lo que se sabía antes del partido**: las patas anteriores que ya tenían
    resultado registrado a la hora del paquete, el global de esas patas y qué hacen al global los primeros 90 minutos de este
    partido. Nunca el ganador, el global final ni cómo se decidió el cruce (eso incluye al propio partido). Lo que pasa si el global
    queda igualado (prórroga, penales, gol de visitante) es la regla de cada competición y **no se supone**;
  * **la tabla del paquete era de otra etapa (defecto encontrado y corregido):** el paquete tomaba, por equipo, la fila más reciente
    de *cualquier* tabla de la temporada y se quedaba con la tabla cuyo nombre ordenaba último. En una temporada con fase regular y
    ronda de campeonato, un partido de la ronda de campeonato se describía con la tabla de la fase regular («Championship Round» <
    «Regular Season»), igual que en Apertura/Clausura; y los partidos que le quedan al equipo contaban toda la temporada, así que los
    de la Clausura ya programados eran «puntos que la tabla de la Apertura todavía podía dar». El Centro de partido tenía el mismo
    defecto hasta el 4 de octubre. Ahora el paquete usa **la misma asignación de tablas que la página** (`competitions.tables`),
    cortada a la hora del paquete: nunca ve una tabla tomada después, lee **una sola** captura, cada lado dice su etapa, su grupo y
    por qué se eligió esa tabla, lo que está en juego (`stakes`) se calcula solo con la etapa propia y una ronda eliminatoria muestra
    la tabla de la etapa anterior como contexto y **sin** «en juego». Una etapa sin tabla propia dice `missing: standings` en vez de
    tomar prestada otra;
  * **dossier-v2:** «es la vuelta» sale de la estructura, no de «el último partido entre los dos equipos en los 60 días anteriores»
    (un partido de grupos 40 días antes convertía una final en «vuelta»); las rondas de clasificación cuentan como eliminatorias;
  * **narrative-v2:** los escenarios de una vuelta, escritos en español;
  * **leak-audit-v2:** nueva regla `tie_legs_known`: toda pata que un paquete guardado cita debe haber empezado antes del partido y
    tener su resultado registrado a la hora del paquete (probada con mutaciones).

## Reglas que se respetan

* **Un equipo juega un rival por ronda.** De ahí salen los cruces, sin conocer la competición: los partidos entre los mismos dos
  equipos en una etapa son un cruce. Si un equipo aparece en dos emparejamientos de la misma etapa (una mini-liga llamada
  «Playoffs»), **no se inventan cruces** y la etapa lo dice (`not_a_bracket`).
* **Apertura y Clausura nunca se mezclan; el partido por el tercer lugar nunca es testigo** de quién pasó.
* **El global es la suma de los goles finales de las patas** (prórroga dentro, penales fuera). Cuando no hay global honesto
  (una pata dada por decisión administrativa sin marcador, o una tanda de penales que los goles contradicen) **no se muestra uno**.
* **Quién pasó sale de los goles, y cuando los goles no lo dicen, de la ronda siguiente** (el equipo que sigue en el mismo cuadro).
  La regla del gol de visitante **no se supone**: donde decidió un cruce, la ronda siguiente coincide. Un ganador que la ronda
  siguiente contradice sigue siendo el ganador en la cancha y queda marcado `contradicted`.
* **El marcador con prórroga del proveedor no siempre es creíble.** En alrededor de 1 de cada 10 partidos con prórroga su bloque
  `extratime` trae el marcador corrido de los 120 minutos en vez de los goles de la prórroga, y su `goals` cuenta dos veces los
  primeros 90 (Riga – CSKA Sofia, 19 jul 2018: 1–0 a los 90, ningún gol en la prórroga, guardado como 2–0). Se corrige con una regla
  del deporte (una tanda de penales solo se juega con el global igualado), el cruce queda marcado `score_repaired` y, si ninguna
  lectura concuerda, el marcador queda desconocido (`score_inconsistent_with_shootout`) en vez de publicarlo mal. **La liquidación
  de apuestas usa el marcador de los 90 minutos y no se toca.**
* **Etiquetas de ronda:** 20 etiquetas cambian de lectura a propósito respecto de `phases-1` (16 pasan de liga a eliminatoria: el
  *Play-In*, la *Reclasificación* mexicana, los *Play Offs*, *Relegation* y los partidos por el 5.º–19.º lugar de un torneo; 4 son
  ids internos del proveedor, `R60310`, `R66244`, `R73389`, `R79396`, que se leen como «sin lectura» en vez de como liga). Una
  copia congelada del lector anterior y una lista cerrada en los tests nombran cada una. Hay 27 partidos con etiquetas que ninguna
  regla lee; quedan fijados con su estado `unresolved`.
* **Sede neutral:** `fbi.catalog.neutral` conserva sus dos expresiones (`FINAL` y `SEMI`) a propósito: su regla (`neutral-v1`) está
  congelada y tiene su propio backtest antes/después; cambiar cómo lee la ronda cambiaría lo que decide. No se toca sin una
  decisión tuya.

## Cómo corre

* **Worker:** trabajo `competition_structure` cada 15 minutos (construye las temporadas nunca construidas, las construidas con
  reglas viejas y las que tienen un partido cerca de hoy, las más cercanas primero, con tope de cantidad y de tiempo) y un barrido
  diario a las 09:40 UTC sobre todas las temporadas, para que un resultado que el proveedor corrige meses después llegue a su cruce.
  Un pase sin cambios no deja fila en el registro de corridas. Se apaga con `FBI_COMPETITION_STRUCTURE=0` sin desplegar. El perro
  guardián lo da por colgado a los 20 minutos.
* **Sin tocar nada si nada cambió:** el resultado de cada temporada lleva una huella; si es la ya guardada, no se escribe (ni
  siquiera `core.fixtures.updated_at`, que otros trabajos leen como «este partido cambió»).
* **A mano, desde `backend/` (0 peticiones al proveedor):**

```bash
python -m scripts.competition_stages build                    # ensayo en seco: las temporadas que toca construir
python -m scripts.competition_stages build --apply            # construirlas, un commit por temporada
python -m scripts.competition_stages build --all --apply      # toda la historia (primer despliegue)
python -m scripts.competition_stages audit                    # cobertura, globales, cruces, contradichos, una muestra
python -m scripts.competition_stages audit --drift --sample 40 --seed 7
python -m scripts.competition_stages show --fixture 456       # las etapas y cruces de la temporada de un partido
```

## Resultado de la prueba general (copia completa de desarrollo, 22 oct 2026)

Toda la historia (245.872 partidos, 1.077 temporadas) se construye en 22 s; una segunda construcción no cambia nada (`drift` 0 de
1.077).

| Medida | Resultado |
|---|---|
| Partidos con etapa | **245.872 de 245.872 (100 %)** — criterio del plan: ≥ 98 % |
| Etapas | 3.851 (eliminatorias 2.165, liga 1.394, clasificación 285, amistosas 3, sin lectura 4) |
| Partidos que son pata de un cruce | 27.027 |
| Cruces | 21.272: 20.997 decididos, 170 programados, 105 sin resolver (con motivo: 64 nunca se jugaron, 14+7 con empate sin evidencia suficiente, 7 aplazados para siempre, 6 sin la vuelta…) |
| Cómo se decidieron | tiempo normal 13.328 · global 3.842 · penales 2.364 · prórroga 1.164 · gol de visitante 201 · desempate 61 · serie 24 · decisión administrativa 13 |
| La ronda siguiente | confirma 19.878 (94,7 % de los decididos) · contradice 22 · no puede decirlo 1.097 (finales y última ronda cargada: no hay ronda siguiente) |
| Globales recalculados en SQL (sin el código del constructor) | **20.082 revisados, 0 distintos, 0 faltantes** (18 sin global a propósito, 17 marcador reparado aparte) |
| Muestra de 40 cruces de ida y vuelta (semilla 2026) | **las patas de los 40 suman su global** |

**Verificación externa (tu criterio de «hecho»: «100 % de una muestra con el global correcto»).** De esa muestra de 40 se
contrastaron **16 contra fuentes ajenas** (UEFA.com, CAF, ESPN, BBC, Wikipedia, worldfootball): Ilves – Austria Viena (5–5, penales
5–4), USM Alger – Zamalek (1–1, penales 8–7), Fenerbahçe – Lyon (3–2), Junior – América de Cali (0–2), Mallorca – Real Sociedad (1–1,
penales 5–4), Orapa United – AS Kigali (2–2, gol de visitante), Young Buffaloes – Le Messager Ngozi (1–1, gol de visitante), Swindon –
Port Vale (2–2, penales 5–6), Vélez – Flamengo (1–6), Lille – Ajax (2–4), Antalyaspor – Alanyaspor (0–5), Leganés – Rayo (3–2),
Nasaf – Al Ain (1–2), Piteå – Brøndby (1–2), Athletico-PR – Flamengo (2–2, penales 3–1) y Patro Eisden – Beerschot (3–4 tras
prórroga). **0 diferencias**; en 14 coinciden todas las patas, el global y la forma de decidir; en Athletico-PR – Flamengo y Patro
Eisden – Beerschot la vuelta coincide y no se encontró nada que contradiga el resto (no se halló una fuente que dé también la ida).
Esto no sustituye una muestra tuya: la auditoría puede imprimir otra (`--sample 40 --seed N`) para que la revises con quien tú
prefieras.

**Los 22 cruces que la ronda siguiente contradice** son decisiones administrativas o errores de datos, no del código: la cancha
decide y quedan marcados `contradicted`. Dos casos comprobados contra la prensa: Barnsley, sacado de la FA Cup 2023-24 por alinear a
un jugador no elegible en la repetición que ganó en la cancha, y Southampton, que ganó la semifinal de ascenso de la Championship
2025-26 en la cancha y fue expulsado de la final por espionaje (Middlesbrough ocupó su lugar). El resto son sobre todo cruces de
rondas previas de FA Cup, Copa de Portugal, Copa del Rey y Coupe de France, y algunas rondas previas africanas, donde el equipo que
ganó no aparece en la ronda siguiente. La lista completa sale con `audit`.

## Lo que se decidió distinto del plan

* **No se añade `standings.stage_id` (no hay migración 0083).** La asignación de tablas ya deduce la etapa de cada tabla en el
  momento de leer; una columna guardada sería una segunda copia que puede discrepar de ella, y ningún lector SQL la necesita hoy. Si
  aparece uno, el lugar es una tabla lateral por (temporada, captura, grupo). Cambia el paquete, no el esquema.

## Cómo deshacerlo

* Parar solo la construcción: `FBI_COMPETITION_STRUCTURE=0` y reiniciar el worker. Con las columnas nulas todo se comporta como
  antes (la API devuelve `stage` y `tie` nulos y la web no pinta nada).
* Quitar todo: `alembic downgrade 0081` borra las dos tablas y las tres columnas (son solo filas derivadas;
  `scripts.competition_stages build --all --apply` las reconstruye). Hacer antes el respaldo habitual de despliegue.
* `packet-v4` corre en producción desde el despliegue de F2 (antes corría `packet-v3`): los paquetes de partidos de temporadas con
  varias tablas son distintos de los de v3 (la corrección de la tabla), es decir, filas nuevas en `ai.match_packets`, que solo se
  añade. Las revisiones de IA que esa novedad provoque quedan dentro de los topes de presupuesto de siempre.

## Resultado en producción (22 oct 2026)

Desplegado a las 16:41 UTC (backend `cc4efa9aba71`, web `0852a8d09069`) con respaldo verificado (1,07 GB), prueba de restauración
superada (604 s, las 12 cuentas de filas coinciden), respaldo propio del despliegue y migración 0082. Todo sigue en SHADOW: nada
de F2 cambia un pick, una probabilidad ni una liquidación.

La construcción de toda la historia (`build --all --apply`) tardó 319 s: 1.077 temporadas, 0 fallos, 25.209 filas escritas y los
246.017 partidos con su etapa, cruce y pata. El ensayo en seco previo había dado exactamente las mismas cifras. La auditoría
(`audit --drift --sample 40 --seed 2026`) pasó todos sus criterios:

| Medida | Producción |
|---|---|
| Partidos con etapa | **246.017 de 246.017 (100 %)** — criterio del plan: ≥ 98 % |
| Etapas | 3.856 (eliminatorias 2.169, liga 1.394, clasificación 286, amistosas 3, sin lectura 4) |
| Partidos de eliminatoria o clasificación que son pata de un cruce | 27.119 de 27.881 (97,3 %); 27 partidos con una ronda que ninguna regla lee (`R60310`, `R66244`, `R73389`, `R79396`) |
| Formato de las rondas | una sola pata 1.586 · ida y vuelta 825 · serie 3 · mezclado 5 · vacías 6 · sin cuadro 30 |
| Cruces | 21.353: 21.063 decididos, 215 programados, 30 en curso, 45 sin resolver (con motivo: 14 empatados sin evidencia de tanda, 7 empatados en el global sin evidencia, 7 aplazados para siempre, 5 nunca jugados, 4 sin la vuelta…) |
| Cómo se decidieron | tiempo normal 13.379 · global 3.846 · penales 2.370 · prórroga 1.169 · gol de visitante 201 · desempate 61 · serie 24 · decisión administrativa 13 |
| La ronda siguiente | confirma 19.945 · contradice **22** · no puede decirlo 1.096 (finales y última ronda cargada) |
| Globales recalculados en SQL (sin el código del constructor) | **20.166 revisados, 0 distintos, 0 faltantes** (19 sin global a propósito, 17 con el marcador reparado aparte) |
| Muestra de 40 cruces de ida y vuelta (semilla 2026) | **las patas de los 40 suman su global** |
| Deriva (repetir la construcción en seco) | **0 de 1.077 temporadas cambiarían** (238 s) |
| Avisos que quedan en los cruces | decidido por la ronda siguiente 757 · tanda sin marcador guardado por el proveedor 511 · vuelta que el proveedor no lista 22 · una sola pata en ronda de ida y vuelta 21 · marcador de prórroga reparado 17 · marcador incoherente con la tanda 3 · patas sin invertir 1 |

**Los 22 cruces contradichos** (la cancha decide y quedan marcados): CAF Champions League 2024 (SC Villa – Ethiopia Nigd Bank),
Libertadores 2019 (Defensor Sporting – Barcelona SC), CAF Confederation Cup 2021 y 2022 (Mangasport – Orapa United; Fasil Ketema –
Bumamuru), Championship 2025 (Middlesbrough – Southampton, el caso comprobado del espionaje), FA Cup (Bottesford – Eastwood,
Bugbrooke – March Town, Barking – Ilford, Haverhill – Mulbarton, Tadley – Portchester, **Barnsley – Horsham**, Cobham – Margate),
EFL Trophy 2025 (Luton – Swindon), Coupe de France 2024 (Étoile Maritime – Vertou; Aigles d'Or – Matoury), DFB Pokal 2021
(Preußen Münster – Wolfsburg), Taça de Portugal (Eirense – Gouveia, Vale Formoso – União de Leiria, Lourinhanense – União
Santarém), Copa del Rey 2023 (Arosa – Granada) y Leagues Cup 2023 (Dallas – Mazatlán; Houston – Pachuca). La lista completa y
actual sale siempre con `audit`.

**Comprobación en vivo.** El servicio que sirve `/matches/{id}/center`, ejecutado dentro del contenedor de la API con su rol de solo
lectura sobre datos reales, devuelve etapa y cruce: la vuelta de la semifinal de Libertadores del 22 oct (global 2-2, pasa el local
en penales 5-3), la de la Sudamericana del 21 oct (global 2-3), las vueltas de mañana con el global de la ida, y un partido de liga
con etapa y sin cruce. Salud del sistema `ok`, `/login` 200, `/auth/me` 401, `/docs` cerrado.

**Lo que queda vigilado.** (1) El barrido diario de las 09:40 UTC (`competition_structure.sweep` en el registro del worker) y la
auditoría de fuga nocturna con la regla nueva `tie_legs_known`. (2) El gasto de IA de los primeros días con `packet-v4`. (3) Los
511 cruces cuya tanda el proveedor no guardó con marcador: se muestran como «en penales» sin cifra, sin inventarla.
