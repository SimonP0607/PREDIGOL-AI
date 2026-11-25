# PM-03-01 · Las 60 candidatas de los lotes 5 a 9: inscritas y sondeadas, sin seguir ninguna (BE-066)

Plan Maestro PM, bloque 3, tarea **PM-03-01**, decisión **DM-03** del dueño (19-nov-2026: lotes 5 a 9, admitiendo niveles C y D).
Es **solo configuración y medición**: las 60 competiciones de los lotes 5 a 9 del anexo A quedan como candidatas en
`config/expansion.yaml`, cada una con su lote previsto (`planned_batch`) y con lo que vio una sonda de solo lectura del 20-nov-2026.
**Desplegar este cambio no sigue nada**: ninguna está en `batches`, así que `scripts.expand_leagues` no puede seguirlas, el
planificador de migración no añade ningún tramo y el worker no les pregunta nada. Cada lote lo escribe su tarea (PM-03-02 a
PM-03-06) cuando el anterior lleve un día UTC medido.

## 1. Qué cambia

* `config/expansion.yaml`:
  * **51 candidatas nuevas** (rangos 59 a 109) con el nombre y el país que da el proveedor en `raw.league_coverage` (temporada más
    reciente, leído el 20-nov a las 06:50 UTC; las 60 coinciden con el anexo A). `expand_leagues` compara justo esos dos campos y
    se niega si difieren, así que un id equivocado se para ahí;
  * las **9 que ya eran candidatas** (36, 129, 263, 269, 887, 101, 43, 59 y 60, del informe de capacidad del 5-oct) solo ganan
    `planned_batch`;
  * una sección nueva **`probes`**, una entrada por sonda: la de hoy (`pm-03-01`) con la medición de cada una y el **nivel esperado
    por familia** según `coverage-levels-v1` (`fbi.coverage.levels`, DM-04).
* `docs/owner/lab/PM_03_01/sonda_lotes_5_9.py.txt`: la orden exacta que se ejecutó dentro del worker.
* `tests/unit/test_expansion_candidates_pm0301.py`: las 60 con su lote, nombre y país; ninguna en un lote; el lote 4 intacto;
  ningún tramo nuevo de migración; cada una con su sonda fechada dentro del tope; y el nivel esperado de cada familia recalculado
  con `fbi.coverage.levels` a partir de las cuotas guardadas.

**Qué no cambia:** los lotes 1 a 4, lo que hoy se sigue (138 competiciones), el worker, la ingesta, umbrales, interruptores,
lectores y la base de datos. Sin migración.

## 2. El lote 4 del Plan AD sigue sin aplicar (no se pisa)

Leído en producción el 20-nov a las 06:50 UTC: Uruguay (268) y Copa Colombia (241) siguen con `is_tracked = false`; el lote 3
(Venezuela 299, Primera B 240) sí está seguido. El lote 4 es del Plan AD (IA-077) y se aplica tras un día UTC medido del lote 3;
este PR no lo toca (la prueba nueva comprueba que sigue siendo `[268, 241]`). **El lote 5 (PM-03-02) no debe escribirse hasta que el
lote 4 esté aplicado y medido un día**: la regla del fichero es «un lote solo tras medir un día el anterior».

## 3. La sonda (20-nov-2026, 06:51–06:55 UTC)

El procedimiento de `scripts.probe_leagues` con las comprobaciones de su módulo (`fbi.catalog.league_probe.judge_detail`), dentro
del worker y con el cliente del propio código, sobre la temporada que `raw.league_coverage` marca como actual:

1. `/fixtures?league&season`: calendario, estados, marcadores y árbitro;
2. `/fixtures?ids=` de los 20 últimos partidos terminados (o los que haya): eventos, alineaciones, estadísticas de equipo y de
   jugador; goles de los eventos frente al marcador en los partidos acabados en 90';
3. `/odds?league&season` (una página) solo si hay partidos en los 14 días siguientes: mediana de casas con precio.

Diferencias deliberadas con `probe_leagues`: **nada se guarda en RAW** (`persist=False`: un `/odds` indexado se convertiría en
precios) y no se abre ninguna ejecución en `raw.ingestion_runs`; las peticiones cuentan en el contador por endpoint con el trabajo
`league_probe` y el carril **`ampliacion`** (PM-01-02); no se pide `/standings` (queda la bandera del proveedor).

**Coste: 203 peticiones** (tope de la ficha: unas 240). Una primera ejecución (06:51 UTC) gastó 60 y se paró por un fallo del guion
(una temporada sin partidos terminados) antes de imprimir nada; la segunda, con tope 180, sondeó las 60 y gastó 143. El contador
del día pasó de 4.241 a 4.587 entre las dos lecturas (incluye el trabajo normal del worker). Fuera de `fixtures_sync`, de la copia
y de la pasada de estadísticas.

**Cómo leer las columnas:** porcentajes sobre la muestra (como mucho 20 partidos); «Alin. 11+11», las dos alineaciones con once
titulares; «Est. equipo», córners, amarillas y tiros totales de los dos equipos; «Árbitro», sobre todos los partidos terminados de
la temporada. El **nivel esperado** es el de `coverage-levels-v1` con esa muestra: **B es lo máximo que puede decir una sonda** (A
exige 30 partidos) y es provisional; MI = menos de 10 partidos. Las familias de cuotas no se califican con una sonda (necesitan los
partidos terminados de la ventana de cuotas): en `expansion.yaml` figura `MI (techo X)`, el techo que permiten sus casas (≥ 5 casas:
A; 3–4: B; < 3: C). «Resumen sin cuotas» es el resumen del directorio con solo los datos de partido (la estrella lo indica).

## 4. Lectura

* **Las 60 existen con el nombre y el país esperados** y ninguna tiene resultados sin resolver. Goles = eventos en el 100 % de los
  partidos en 90' salvo la FA Cup de Escocia (181): 14 de 15 (un 3-1 con cinco goles en eventos).
* **Lo que de verdad aportan es base (resultado, eventos y, a veces, alineaciones)**. Estadísticas de equipo solo en tres:
  clasificación de la Copa Africana (36, 100 %), Liga de Expansión MX (263, 80 %) y League Cup de Escocia (185, 45 %); de jugador,
  solo 36 y 263. Coincide con el techo que declara el anexo A («C como máximo» en 57 de 62).
* **Alineaciones**: 16 de las 60 no traen ninguna en la muestra, entre ellas siete de los ocho del lote 9 (todo lo inglés por debajo de
  la National League, que sí las trae) y las dos copas escocesas menores (181, 182). Su base queda en **D**: con DM-03 se admiten,
  pero la matriz las mostrará como limitadas.
* **Clasificación de la Copa Africana (36)**: estadísticas completas pero alineaciones en el 10 %: base D aunque «equipo» y
  «jugador» lleguen a B. Su próximo partido es de marzo de 2027.
* **Ediciones de 2026 ya terminadas**: 23 de las 60 no tienen partidos por jugar (supercopas de un partido, Superliga y Recopa de
  enero y febrero, Copa Australia, US Open Cup, Liga Femenina, Liga Panameña, Segunda de Uruguay…). Seguirlas hoy no trae nada:
  su valor empieza con la edición siguiente, que el proveedor aún no lista. Las supercopas (1 a 4 partidos) quedarán en **MI** por
  muestra; el nivel se hereda o se mide al acumular ediciones (regla de `coverage-levels-v1`).
* **Supercopa de Bélgica (519)** no tiene partidos en su temporada 2026 y **Supercopa de Emiratos (896)** tiene uno por jugar (29-nov):
  sin muestra.
* **Cuotas**: donde se pidieron con partido en la página, la mediana va de 3 (Copa Chile) a 10 casas; techo A en casi todas. En el
  lote 9 la base es D pero las cuotas existen (8 a 10 casas): es el caso que la sección 3 del plan describe («puede capturar solo
  cuotas principales»).

| Lote | Comp. | Resumen esperado sin cuotas | Base esperada |
| --- | ---: | --- | --- |
| 5 | 6 | C\* 1 · D 3 · MI 2 | B 1 · C 2 · D 1 · MI 2 |
| 6 | 16 | B\* 1 · C\* 5 · D 3 · MI 7 | B 6 · D 3 · MI 7 |
| 7 | 9 | C\* 5 · D 2 · MI 2 | B 5 · D 2 · MI 2 |
| 8 | 21 | C\* 8 · D 9 · MI 4 | B 8 · C 3 · D 6 · MI 4 |
| 9 | 8 | C\* 1 · D 7 | B 1 · D 7 |

## 5. Lo que sigue (no lo hace este PR)

1. Lote 4 (Plan AD): aplicarlo y medir un día UTC (guía `IA_077_COBERTURA_CUATRO_LIGAS.md`, §4).
2. **PM-03-02 · lote 5**: escribir el lote en `batches` con su `probe: pm-03-01` y su `measured`, por PR; desplegar; el dueño ejecuta
   `python -m scripts.expand_leagues --batch 5` (ensayo) y `--apply`, fuera de `fixtures_sync` (hoy a las 03:55, 09:55, 15:55 y
   21:55 UTC; 20 min de margen) y nunca entre las 03:30 y las 05:00 UTC; un día medido con `python -m scripts.capture_odds status`
   (≤ 1.000 peticiones añadidas). Después los lotes 6 a 9 (PM-03-03 a PM-03-06), uno tras otro.
3. Para un lote cuya edición 2026 ya terminó, conviene esperar a que el proveedor liste la siguiente (el ensayo de
   `expand_leagues` muestra `current`).
4. Repetir la sonda antes de escribir un lote si han pasado semanas (la muestra son los 20 últimos partidos): la orden está en
   `docs/owner/lab/PM_03_01/` y su coste es de unas 2,4 peticiones por competición.

## 6. Vuelta atrás

`revert` de este PR: quita candidatas y sonda; no hay nada seguido ni nada en la base que deshacer (la sonda no guardó nada en RAW
y no abrió ninguna ejecución). Las 203 peticiones ya están gastadas.

## 7. Detalle por lote

Los mismos datos que `probes` de `config/expansion.yaml`, en tablas.

### Lote 5

| Id | Competición | Temp. | Partidos (term. / por jugar) | Muestra | Eventos | Alin. 11+11 | Est. equipo | xG | Jugadores | Árbitro | Goles = eventos | Casas (partidos) | Nivel esperado: base · equipo · jugador · árbitro | Resumen sin cuotas | Techo del proveedor (anexo A) |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|
| 713 | Superliga (Colombia) | 2026 | 2 (2 / 0) | 2 | 100 % | 100 % | 0 % | 0 % | 0 % | 0 % | 100 % | sin pedir | MI · MI · MI · MI | MI | C como máximo |
| 712 | Liga Femenina (Colombia) | 2026 | 158 (158 / 0) | 20 | 100 % | 75 % | 0 % | 0 % | 0 % | 1 % | 100 % | sin pedir | C · D · D · D | D | C como máximo |
| 541 | CONMEBOL Recopa (World) | 2026 | 2 (2 / 0) | 2 | 100 % | 100 % | 0 % | 0 % | 0 % | 0 % | 100 % | sin pedir | MI · MI · MI · MI | MI | C como máximo |
| 27 | OFC Champions League (World) | 2026 | 21 (21 / 0) | 20 | 100 % | 75 % | 0 % | 0 % | 0 % | 0 % | 100 % | sin pedir | C · D · D · D | D | C como máximo |
| 1132 | AFC Challenge League (World) | 2026 | 47 (36 / 8) | 20 | 100 % | 80 % | 0 % | 0 % | 0 % | 75 % | 100 % | sin pedir | B · D · D · C | C* | C como máximo |
| 36 | Africa Cup of Nations - Qualification (World) | 2027 | 156 (108 / 48) | 20 | 100 % | 10 % | 100 % | 100 % | 100 % | 75 % | 100 % | sin pedir | D · B · B · C | D | A o B posible |

### Lote 6

| Id | Competición | Temp. | Partidos (term. / por jugar) | Muestra | Eventos | Alin. 11+11 | Est. equipo | xG | Jugadores | Árbitro | Goles = eventos | Casas (partidos) | Nivel esperado: base · equipo · jugador · árbitro | Resumen sin cuotas | Techo del proveedor (anexo A) |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|
| 129 | Primera Nacional (Argentina) | 2026 | 664 (655 / 8) | 20 | 100 % | 100 % | 0 % | 0 % | 0 % | 1 % | 100 % | 10 (10) | B · D · D · D | C* | C como máximo |
| 130 | Copa Argentina (Argentina) | 2026 | 63 (62 / 1) | 20 | 100 % | 95 % | 0 % | 0 % | 0 % | 48 % | 100 % | 10 (1) | B · D · D · D | C* | C como máximo |
| 517 | Trofeo de Campeones de la Superliga (Argentina) | 2026 | 1 (1 / 0) | 1 | 100 % | 100 % | 0 % | 0 % | 0 % | 0 % | 100 % | sin pedir | MI · MI · MI · MI | MI | C como máximo |
| 810 | Super Copa (Argentina) | 2026 | 1 (1 / 0) | 1 | 100 % | 100 % | 0 % | 0 % | 0 % | 100 % | — | sin pedir | MI · MI · MI · MI | MI | C como máximo |
| 1178 | Super Copa International (Argentina) | 2026 | 1 (1 / 0) | 1 | 100 % | 100 % | 0 % | 0 % | 0 % | 100 % | 100 % | sin pedir | MI · MI · MI · MI | MI | C como máximo |
| 632 | Supercopa do Brasil (Brazil) | 2026 | 1 (1 / 0) | 1 | 100 % | 100 % | 0 % | 0 % | 0 % | 0 % | 100 % | sin pedir | MI · MI · MI · MI | MI | C como máximo |
| 266 | Primera B (Chile) | 2026 | 247 (240 / 7) | 20 | 100 % | 100 % | 0 % | 0 % | 0 % | 1 % | 100 % | 10 (10) | B · D · D · D | C* | C como máximo |
| 267 | Copa Chile (Chile) | 2026 | 120 (119 / 1) | 20 | 100 % | 100 % | 0 % | 0 % | 0 % | 20 % | 100 % | 3 (1) | B · D · D · D | C* | C como máximo |
| 527 | Super Cup (Chile) | 2026 | 3 (3 / 0) | 3 | 100 % | 100 % | 0 % | 0 % | 0 % | 33 % | 100 % | sin pedir | MI · MI · MI · MI | MI | C como máximo |
| 263 | Liga de Expansión MX (Mexico) | 2026 | 134 (132 / 2) | 20 | 100 % | 95 % | 80 % | 40 % | 80 % | 99 % | 100 % | 9 (3) | B · B · B · A | B* | A o B posible |
| 857 | Campeón de Campeones (Mexico) | 2026 | 1 (1 / 0) | 1 | 100 % | 100 % | 0 % | 0 % | 0 % | 100 % | 100 % | sin pedir | MI · MI · MI · MI | MI | C como máximo |
| 304 | Liga Panameña de Fútbol (Panama) | 2026 | 201 (201 / 0) | 20 | 100 % | 30 % | 0 % | 0 % | 0 % | 0 % | 100 % | sin pedir | D · D · D · D | D | C como máximo |
| 257 | US Open Cup (USA) | 2026 | 79 (78 / 0) | 20 | 100 % | 100 % | 0 % | 0 % | 0 % | 40 % | 100 % | sin pedir | B · D · D · D | C* | C como máximo |
| 269 | Segunda División (Uruguay) | 2026 | 229 (229 / 0) | 20 | 95 % | 0 % | 0 % | 0 % | 0 % | 0 % | 100 % | sin pedir | D · D · D · D | D | C como máximo |
| 842 | Super Copa (Uruguay) | 2026 | 1 (1 / 0) | 1 | 100 % | 100 % | 0 % | 0 % | 0 % | 100 % | — | sin pedir | MI · MI · MI · MI | MI | C como máximo |
| 930 | Copa Uruguay (Uruguay) | 2026 | 58 (56 / 0) | 20 | 100 % | 0 % | 0 % | 0 % | 0 % | 0 % | 100 % | sin pedir | D · D · D · D | D | C como máximo |

### Lote 7

| Id | Competición | Temp. | Partidos (term. / por jugar) | Muestra | Eventos | Alin. 11+11 | Est. equipo | xG | Jugadores | Árbitro | Goles = eventos | Casas (partidos) | Nivel esperado: base · equipo · jugador · árbitro | Resumen sin cuotas | Techo del proveedor (anexo A) |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|
| 220 | Cup (Austria) | 2026 | 60 (56 / 4) | 20 | 100 % | 100 % | 0 % | 0 % | 0 % | 14 % | 100 % | sin pedir | B · D · D · D | C* | C como máximo |
| 147 | Cup (Belgium) | 2026 | 40 (32 / 8) | 20 | 100 % | 80 % | 0 % | 0 % | 0 % | 0 % | 100 % | sin pedir | B · D · D · D | C* | C como máximo |
| 519 | Super Cup (Belgium) | 2026 | 0 (0 / 0) | 0 | — | — | — | — | — | — | — | sin pedir | MI · MI · MI · MI | MI | C como máximo |
| 120 | 1. Division (Denmark) | 2026 | 132 (85 / 47) | 20 | 100 % | 95 % | 0 % | 0 % | 0 % | 100 % | 100 % | 10 (6) | B · D · D · A | C* | C como máximo |
| 121 | DBU Pokalen (Denmark) | 2026 | 104 (96 / 8) | 20 | 100 % | 100 % | 0 % | 0 % | 0 % | 8 % | 100 % | 0 partidos | B · D · D · D | C* | C como máximo |
| 550 | Super Cup (Portugal) | 2026 | 1 (1 / 0) | 1 | 100 % | 100 % | 0 % | 0 % | 0 % | 100 % | 100 % | sin pedir | MI · MI · MI · MI | MI | C como máximo |
| 181 | FA Cup (Scotland) | 2026 | 70 (50 / 20) | 20 | 100 % | 0 % | 0 % | 0 % | 0 % | 0 % | 93 % | 0 partidos | D · D · D · D | D | C como máximo |
| 182 | Challenge Cup (Scotland) | 2026 | 144 (136 / 8) | 20 | 100 % | 0 % | 0 % | 0 % | 0 % | 0 % | 100 % | 0 partidos | D · D · D · D | D | C como máximo |
| 185 | League Cup (Scotland) | 2026 | 95 (94 / 1) | 20 | 100 % | 100 % | 20 % | 0 % | 0 % | 16 % | 100 % | sin pedir | B · D · D · D | C* | A o B posible |

### Lote 8

| Id | Competición | Temp. | Partidos (term. / por jugar) | Muestra | Eventos | Alin. 11+11 | Est. equipo | xG | Jugadores | Árbitro | Goles = eventos | Casas (partidos) | Nivel esperado: base · equipo · jugador · árbitro | Resumen sin cuotas | Techo del proveedor (anexo A) |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|
| 874 | Australia Cup (Australia) | 2026 | 31 (31 / 0) | 20 | 100 % | 100 % | 0 % | 0 % | 0 % | 97 % | 100 % | sin pedir | B · D · D · A | C* | C como máximo |
| 1202 | Australian Championship (Australia) | 2026 | 48 (42 / 6) | 20 | 100 % | 0 % | 0 % | 0 % | 0 % | 0 % | 100 % | 9 (10) | D · D · D · D | D | C como máximo |
| 539 | Super Cup (Egypt) | 2026 | 4 (4 / 0) | 4 | 100 % | 100 % | 0 % | 0 % | 0 % | 0 % | 100 % | sin pedir | MI · MI · MI · MI | MI | C como máximo |
| 887 | Second League (Egypt) | 2026 | 380 (124 / 255) | 20 | 90 % | 0 % | 0 % | 0 % | 0 % | 0 % | 100 % | 9 (10) | D · D · D · D | D | C como máximo |
| 895 | League Cup (Egypt) | 2026 | 40 (16 / 24) | 16 | 100 % | 50 % | 0 % | 0 % | 0 % | 0 % | 100 % | 0 partidos | C · D · D · D | D | C como máximo |
| 324 | I-League (India) | 2026 | 55 (18 / 37) | 18 | 100 % | 83 % | 0 % | 0 % | 0 % | 100 % | 100 % | 0 partidos | B · D · D · B | C* | C como máximo |
| 545 | AIFF Super Cup (India) | 2026 | 27 (27 / 0) | 20 | 100 % | 100 % | 0 % | 0 % | 0 % | 19 % | 100 % | sin pedir | B · D · D · D | C* | C como máximo |
| 101 | J-League Cup (Japan) | 2026 | 64 (60 / 4) | 20 | 100 % | 100 % | 0 % | 0 % | 0 % | 12 % | 100 % | sin pedir | B · D · D · D | C* | C como máximo |
| 102 | Emperor Cup (Japan) | 2026 | 80 (72 / 8) | 20 | 100 % | 100 % | 0 % | 0 % | 0 % | 0 % | 100 % | sin pedir | B · D · D · D | C* | C como máximo |
| 306 | Second Division (Qatar) | 2026 | 72 (36 / 36) | 20 | 95 % | 0 % | 0 % | 0 % | 0 % | 0 % | 100 % | 6 (1) | D · D · D · D | D | C como máximo |
| 677 | QSL Cup (Qatar) | 2026 | 36 (18 / 18) | 18 | 100 % | 0 % | 0 % | 0 % | 0 % | 17 % | 100 % | sin pedir | D · D · D · D | D | C como máximo |
| 824 | Emir Cup (Qatar) | 2026 | 19 (19 / 0) | 19 | 100 % | 79 % | 0 % | 0 % | 0 % | 37 % | 100 % | sin pedir | C · D · D · D | D | C como máximo |
| 825 | Qatar Cup (Qatar) | 2025 | 3 (2 / 1) | 2 | 100 % | 100 % | 0 % | 0 % | 0 % | 100 % | 100 % | sin pedir | MI · MI · MI · MI | MI | C como máximo |
| 308 | Division 1 (Saudi-Arabia) | 2026 | 171 (95 / 76) | 20 | 100 % | 95 % | 0 % | 0 % | 0 % | 97 % | 100 % | 8 (1) | B · D · D · A | C* | C como máximo |
| 826 | Super Cup (Saudi-Arabia) | 2026 | 3 (3 / 0) | 3 | 100 % | 100 % | 0 % | 0 % | 0 % | 100 % | 100 % | sin pedir | MI · MI · MI · MI | MI | C como máximo |
| 293 | K League 2 (South-Korea) | 2026 | 272 (256 / 16) | 20 | 100 % | 100 % | 0 % | 0 % | 0 % | 100 % | 100 % | 10 (8) | B · D · D · A | C* | C como máximo |
| 294 | FA Cup (South-Korea) | 2026 | 55 (55 / 0) | 20 | 100 % | 40 % | 0 % | 0 % | 0 % | 0 % | 100 % | sin pedir | D · D · D · D | D | C como máximo |
| 302 | League Cup (United-Arab-Emirates) | 2026 | 42 (28 / 14) | 20 | 100 % | 65 % | 0 % | 0 % | 0 % | 71 % | 100 % | sin pedir | C · D · D · C | D | C como máximo |
| 303 | Division 1 (United-Arab-Emirates) | 2026 | 112 (63 / 49) | 20 | 100 % | 0 % | 0 % | 0 % | 0 % | 0 % | 100 % | 6.5 (6) | D · D · D · D | D | C como máximo |
| 560 | Presidents Cup (United-Arab-Emirates) | 2026 | 25 (21 / 4) | 20 | 100 % | 100 % | 0 % | 0 % | 0 % | 38 % | 100 % | sin pedir | B · D · D · D | C* | C como máximo |
| 896 | Super Cup (United-Arab-Emirates) | 2026 | 1 (0 / 1) | 0 | — | — | — | — | — | — | — | 0 partidos | MI · MI · MI · MI | MI | D como máximo |

### Lote 9

| Id | Competición | Temp. | Partidos (term. / por jugar) | Muestra | Eventos | Alin. 11+11 | Est. equipo | xG | Jugadores | Árbitro | Goles = eventos | Casas (partidos) | Nivel esperado: base · equipo · jugador · árbitro | Resumen sin cuotas | Techo del proveedor (anexo A) |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|
| 43 | National League (England) | 2026 | 552 (200 / 349) | 20 | 100 % | 100 % | 0 % | 0 % | 0 % | 41 % | 100 % | 10 (10) | B · D · D · D | C* | C como máximo |
| 47 | FA Trophy (England) | 2026 | 288 (256 / 32) | 20 | 100 % | 0 % | 0 % | 0 % | 0 % | 0 % | 100 % | sin pedir | D · D · D · D | D | C como máximo |
| 50 | National League - North (England) | 2026 | 552 (187 / 364) | 20 | 95 % | 0 % | 0 % | 0 % | 0 % | 0 % | 100 % | 8.5 (10) | D · D · D · D | D | C como máximo |
| 51 | National League - South (England) | 2026 | 552 (188 / 363) | 20 | 95 % | 0 % | 0 % | 0 % | 0 % | 0 % | 100 % | 8 (10) | D · D · D · D | D | C como máximo |
| 58 | Non League Premier - Isthmian (England) | 2026 | 462 (182 / 280) | 20 | 90 % | 0 % | 0 % | 0 % | 0 % | 0 % | 100 % | 8 (10) | D · D · D · D | D | C como máximo |
| 59 | Non League Premier - Northern (England) | 2026 | 462 (200 / 261) | 20 | 100 % | 0 % | 0 % | 0 % | 0 % | 0 % | 100 % | 9 (10) | D · D · D · D | D | C como máximo |
| 60 | Non League Premier - Southern South (England) | 2026 | 462 (183 / 263) | 20 | 95 % | 0 % | 0 % | 0 % | 0 % | 0 % | 100 % | 9 (10) | D · D · D · D | D | C como máximo |
| 931 | Non League Premier - Southern Central (England) | 2026 | 462 (186 / 271) | 20 | 100 % | 0 % | 0 % | 0 % | 0 % | 0 % | 100 % | 9 (10) | D · D · D · D | D | C como máximo |

## 8. Lote 5 escrito (OPS-015, PM-03-02, 23-nov-2026)

El lote 4 del Plan AD se aplicó el 20-nov-2026 y se midió el 21 y el 22-nov completos (OPS-014, §6 de `IA_077_COBERTURA_CUATRO_LIGAS.md`):
dentro del criterio. Con eso, `config/expansion.yaml` lleva el **lote 5** (nivel de migración 9): Superliga (713) y Liga Femenina (712)
de Colombia, CONMEBOL Recopa (541), OFC Champions League (27), AFC Challenge League (1132) y clasificación de la Copa Africana (36),
decidido con la sonda `pm-03-01`, repetida el 24-nov-2026 a las 21:07 UTC para estas 16 (40 peticiones, nada en RAW; `pm0303_sonda_lote6.sh`), y la regla DM-03 (se admiten niveles C y D; la matriz gradúa cada familia). Escribirlo no sigue nada.

Tras el despliegue (0 peticiones, fuera de `fixtures_sync` y nunca entre 03:30 y 05:00 UTC):

1. Ensayo: `docker exec -w /app predigol-worker python -m scripts.expand_leagues --batch 5`. Debe listar las seis con `known` y
   `tracked False`; si dice `REFUSED`, se para.
2. Seguimiento: la misma orden con `--apply`. Seguidas 140 → 146.
3. La clasificación de la Copa Africana es de selecciones: cuando sus equipos estén guardados, `python -m scripts.sync_teams
   --scopes-only` (0 peticiones), como en el lote 2.
4. Medir el día UTC completo siguiente (consumo, capturas y nivel), con el criterio de IA-077 (≤ 1.000 peticiones añadidas).

Esperado: ≈ 80 peticiones al día de media y ≈ 720 el día de más carga; Superliga y Recopa quedan en «muestra insuficiente» (una
eliminatoria al año). Vuelta atrás: `--batch 5 --untrack --apply` (no borra nada).

## 9. Lote 6 escrito (OPS-018, PM-03-03, 2026-11-24)

El lote 5 está seguido y medido (medido por ventana de horas, §7 de IA-077). Con eso, `config/expansion.yaml` lleva el **lote 6** (nivel de migración 10): segundas, copas y supercopas de América (Argentina, Brasil, Chile, Uruguay, México, Estados Unidos y Panamá) — 16 competiciones (129, 130, 517, 810, 1178, 632, 266, 267, 527, 263, 857, 304, 257, 269, 842, 930), decidido con la sonda `pm-03-01` y la regla DM-03 (se admiten niveles C y D; la matriz gradúa cada familia). Escribirlo no sigue nada.

Tras el despliegue (0 peticiones, fuera de `fixtures_sync` y nunca entre 03:30 y 05:00 UTC):

1. Ensayo: `docker exec -w /app predigol-worker python -m scripts.expand_leagues --batch 6`. Debe listar las 16 con `known` y `tracked False`; si dice `REFUSED`, se para.
2. Seguimiento: la misma orden con `--apply`.
3. Medir la ventana (o el día UTC completo) siguiente con el criterio de IA-077 (≤ 1.000 peticiones añadidas), antes del lote siguiente.

Repetición del 24-nov (4 días después): las 16 contestaron y los datos del 20-nov se confirman (mismos partidos y mismas banderas; el nivel esperado sin cuotas solo
cambia en 304 Liga Panameña, que pasa de D a C* porque ya hay alineaciones en la muestra). Hay **16 partidos por jugar en 14 días** (129: 4, 266: 3, 304: 2, 269: 2, 930: 2, 130: 1, 267: 1, 263: 1), así que el
lote tendrá partidos propios (cuotas, alineaciones y eventos) desde el primer día de medición.

Esperado: ≈ 320 peticiones al día de media y ≈ 2.000 el día de más carga (2,2 GB al año, sobre todo cuotas). Nivel esperado: 263 Liga de Expansión MX alcanza B* (estadísticas, xG, jugadores y árbitro declarados); 129, 130, 266, 267 y 257 quedan en C*; 304, 269 y 930 en D; los siete partidos únicos (517, 810, 1178, 632, 527, 857, 842) en «muestra insuficiente». Vuelta atrás: `--batch 6 --untrack --apply` (no borra nada).

## 10. Lote 7 escrito (OPS-020, PM-03-04, 2026-11-25)

Condición del alta: el lote 6 se sigue (OPS-018) y se mide por ventana de horas: al menos un ciclo de `fixtures_sync` tras su alta y partidos suyos jugados o en curso, con ≤ 1.000 peticiones añadidas (criterio de IA-077); si aún no hubo ni ciclo ni partido, el alta de este lote espera ese ciclo (horas, no días). Con ese criterio, `config/expansion.yaml` lleva el **lote 7** (nivel de migración 11): segundas, copas y supercopas de Europa (Austria, Bélgica, Dinamarca, Portugal y Escocia) — 9 competiciones (220, 147, 519, 120, 121, 550, 181, 182, 185), decidido con la sonda `pm-03-01`, repetida (si el alta lo pide) justo antes de seguirlo y la regla DM-03 (se admiten niveles C y D; la matriz gradúa cada familia). Escribirlo no sigue nada.

Tras el despliegue (0 peticiones, fuera de `fixtures_sync` y nunca entre 03:30 y 05:00 UTC):

1. Ensayo: `docker exec -w /app predigol-worker python -m scripts.expand_leagues --batch 7`. Debe listar las 9 con `known` y `tracked False`; si dice `REFUSED`, se para.
2. Seguimiento: la misma orden con `--apply`.
3. Medir la ventana (o el día UTC completo) siguiente con el criterio de IA-077 (≤ 1.000 peticiones añadidas), antes del lote siguiente.

Esperado: ≈ 140 peticiones al día de media y ≈ 1.300 el día de más carga (0,3 GB al año). Nivel esperado: 220, 147, 120, 121 y 185 en C*; 181 y 182 en D (sin alineaciones declaradas); 519 y 550 en «muestra insuficiente». Vuelta atrás: `--batch 7 --untrack --apply` (no borra nada).

## 11. Lote 8 escrito (OPS-021, PM-03-05, 2026-11-25)

Condición del alta: el lote 7 se sigue (OPS-020) y se mide por ventana de horas: al menos un ciclo de `fixtures_sync` tras su alta y partidos suyos jugados o en curso, con ≤ 1.000 peticiones añadidas (criterio de IA-077); si aún no hubo ni ciclo ni partido, el alta de este lote espera ese ciclo (horas, no días). Con ese criterio, `config/expansion.yaml` lleva el **lote 8** (nivel de migración 12): Asia, África y Oceanía (Australia, Egipto, India, Japón, Catar, Arabia Saudita, Corea del Sur y Emiratos) — 21 competiciones (874, 1202, 539, 887, 895, 324, 545, 101, 102, 306, 677, 824, 825, 308, 826, 293, 294, 302, 303, 560, 896), decidido con la sonda `pm-03-01`, repetida (si el alta lo pide) justo antes de seguirlo y la regla DM-03 (se admiten niveles C y D; la matriz gradúa cada familia). Escribirlo no sigue nada.

Tras el despliegue (0 peticiones, fuera de `fixtures_sync` y nunca entre 03:30 y 05:00 UTC):

1. Ensayo: `docker exec -w /app predigol-worker python -m scripts.expand_leagues --batch 8`. Debe listar las 21 con `known` y `tracked False`; si dice `REFUSED`, se para.
2. Seguimiento: la misma orden con `--apply`.
3. Medir la ventana (o el día UTC completo) siguiente con el criterio de IA-077 (≤ 1.000 peticiones añadidas), antes del lote siguiente.

Esperado: ≈ 350 peticiones al día de media y ≈ 2.050 el día de más carga (1,6 GB al año). Nivel esperado: nueve en C* (base B), tres o cuatro en C o D, seis en D por falta de alineaciones, cuatro en «muestra insuficiente»; ninguna activación en 03:30-05:00 UTC. Vuelta atrás: `--batch 8 --untrack --apply` (no borra nada).

