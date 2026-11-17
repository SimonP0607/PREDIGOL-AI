# IA-094 · Titularidad estimada (AD-D04)

Pieza AD-D04 del plan de la arquitectura definitiva 2026 (responsable: Modelos). No existe una «alineación probable» guardada en ningún sitio (producción, 16-nov-2026). Antes de la alineación oficial —que llega 20 minutos antes del saque en la mediana (AD-D05)— nada dice, con datos y con fuente, qué probabilidad tiene cada jugador de ser titular. Esta pieza lo estima, lo guarda con su momento y lo **mide contra la alineación oficial real**.

**Todo en sombra.** Nada de esto llega al lector, a un pick, a `decision-v1` ni a `decision-v2`. `FBI_PICKS_SOURCE` sigue apagado. Ningún modelo de lenguaje calcula ni corrige una cifra. **Sin datos médicos**: una baja es una de cuatro palabras (disponible, duda, baja, sancionado) con su base (IA-091); el motivo de la lesión no se lee ni se guarda.

## 1. Cómo se estima (`lineup-estimate-v1`, `fbi/players/lineup_estimate.py`)

Por jugador de cada equipo, en un momento, con tres entradas:

1. **Minutos recientes** (`player-engine-v1`): la proporción, ponderada por recencia, de los últimos 10 partidos del equipo en que fue titular, si fue titular en el último y si está en duda; calibrada con un modelo logístico que se reajusta con lo conocido antes (cada 30 días). `sample` = partidos del equipo detrás de la proporción.
2. **Bajas confirmadas** (IA-091): «baja» o «sancionado» con base **oficial, proveedor o dos orígenes** → no es titular (`baja_confirmada`). «Duda», o una baja que solo da **un medio**, es una duda: entra en el modelo como variable, nunca como regla. Un rumor no cambia nada.
3. **Hechos «titular» con fuente** (`ai.evidence`, elementos de alineación que nombran al jugador): el peldaño más alto multiplica las probabilidades a favor por un factor fijo: **oficial ×9, dos orígenes ×4, un medio ×2, rumor ×1** (nada). Son **ajustes fijados antes de medir**, no cifras ajustadas a los datos.

Cuando la alineación oficial está leída en ese momento, manda ella: titular 1, banquillo 0 (y entra con su tasa), fuera de la hoja 0.

**Sello.** Cada cifra lleva `calibrada` o `sin_calibrar`. Es `calibrada` solo para una competición que esté en la lista `CALIBRATED`, que **está vacía**: una competición entra cuando tú firmas una medición que bata a la línea base allí con la muestra preregistrada (**60 lados** con alineación oficial: tres jornadas de una liga de 20). Hasta entonces, todo dice `sin_calibrar`.

## 2. Qué se guarda (migración 0151, solo añadido)

`intel.lineup_estimates`: una fila por jugador, equipo, partido y evaluación (**E1**, de T-24 a T-12 h; **E4**, de T-20 a T-10 min, las mismas ventanas que IA-093; no cambian con IA-142: el E4 del ciclo pasó a T-5 el 17-nov-2026, pero no lee esta estimación, que sigue acompañando a la última decisión de `decision-v2`): probabilidad de titular y de jugar, minutos esperados, base, muestra, estado y base de la baja, peldaño e ids de los hechos usados, sello, si la oficial ya estaba leída, versiones y momento. La base rechaza una estimación posterior al saque, una baja confirmada con probabilidad mayor que 0 y una base que no sea de la lista. `UPDATE` y `DELETE` rechazados (`ai.refuse_change()`).

El trabajo `lineup_estimate_shadow` **nace apagado** (`FBI_LINEUP_ESTIMATE=off`). En `shadow`, cada 5 minutos estima como mucho 12 partidos seguidos que estén en su ventana y no tengan aún esa evaluación. Lee los partidos jugados de 180 días de la competición y de los dos equipos, las bajas del proveedor y de la prensa hasta ese momento, los hechos «titular» y la hoja oficial si existe. Sin proveedor, sin modelo de lenguaje.

## 3. Medición frente a la alineación oficial (producción, solo lectura, 17-nov-2026)

**Método.** Exporté de producción (solo lectura) los datos de jugador de 210 días (452.876 filas de estadísticas, 11.008 partidos jugados), las bajas del proveedor, las alineaciones oficiales (titulares de `core.fixture_lineup_players`) y los hechos de la prensa (sin texto), y lo procesé en la imagen del worker **sin red**. Cada lado de cada partido de las competiciones seguidas que se jugó del **18-oct al 17-nov-2026** se estimó **90 minutos antes del saque** (antes de la oficial), con solo lo conocido entonces, y se comparó con los titulares oficiales. Línea base de la ficha: **«el mismo once que el partido anterior del equipo»** (1 a quien fue titular, 0 al resto). Un titular que el historial nunca vio cuenta con probabilidad 0 en las dos.

**Hallazgo previo (dato, no del modelo).** Las estadísticas del proveedor marcan **14,47 titulares por equipo** y las alineaciones oficiales **10,79** (4.575 lados, mismos partidos): `is_substitute` vale «falso» para jugadores que entraron desde el banquillo. `player-engine-v1` leía al titular de las estadísticas y aprendía de una etiqueta equivocada (calibración ECE 0,142, media 0,51 frente a 0,39 real). `lineup-estimate-v1` lee al titular **de la hoja** cuando existe (`prefer_sheet`); `player-engine-v1` queda **exactamente como estaba** (su valor por omisión no cambia) — corregirlo es decisión aparte.

**Resultado (muestra: 4.574 lados de 2.292 partidos; 125.935 estimaciones de jugador; 49.343 titulares oficiales, 1.733 de ellos sin historial):**

| Medida | `lineup-estimate-v1` | Línea base «mismo once» |
| --- | --- | --- |
| Brier (menor es mejor) | **0,148** | 0,203 |
| Brier sin bajas ni hechos (solo minutos) | 0,150 | — |
| Error de calibración (ECE) | **0,030** | — |
| Precisión de los 11 más probables (= recall) | 0,741 | 0,744 |
| Con umbral 0,5: precisión / recall | 0,773 / 0,679 | — |

Calibración por tramos: de 0,0–0,1 (media 0,07, real 0,09) a 0,8–0,9 (media 0,86, real 0,87); el mayor desvío, 0,4–0,5 (0,45 frente a 0,53).

**Por competición** (84 competiciones; 32 con la muestra preregistrada de 60 lados): **31 baten a la línea base en Brier, 1 no**: la **UEFA Nations League** (Brier 0,407 frente a 0,309; precisión del once 0,34 frente a 0,62). Con selecciones, el candidato es quien jugó su último partido con ese equipo, y el historial de un internacional es el de su club: hacen falta las convocatorias (IA-092). Ejemplos: Premier League 0,143 frente a 0,280 (70 lados), Serie A 0,128 frente a 0,208 (92), LaLiga 0,136 frente a 0,221 (72), Primera A de Colombia 0,154 frente a 0,207 (120), MLS 0,132 frente a 0,199 (136). Las 52 competiciones restantes (1.973 lados) no tienen muestra para un veredicto.

**Lectura honesta.**
- En **probabilidad** (Brier, calibración) la estimación es claramente mejor que «el mismo once»; esa línea base es 0/1 y se castiga mucho cuando falla.
- En **elegir a los once** empata con la línea base (74,1 % frente a 74,4 %). Hoy no aporta un once mejor que mirar el partido anterior; aporta **probabilidades calibradas** para cada jugador, que es lo que necesitan AD-B08 y AD-D03.
- Las **bajas** aportan poco al total (0,150 → 0,148): 1.914 estimaciones fueron bajas confirmadas.
- Los **hechos «titular»** casi no existen con jugador identificado: de 4.610 elementos de alineación de la prensa en el periodo, **4.430 no traen id de jugador** (solo el nombre) y no se pueden enlazar todavía; con id hay 180 (de Research v2). Se usaron en 38 estimaciones (31 fueron titulares). Muestra demasiado pequeña para juzgar los factores.

Ninguna competición se ha marcado `calibrada`: eso queda para tu firma.

## 4. Pruebas

- **Unitarias**: una baja confirmada nunca es titular; duda o un solo medio es variable, no regla; los hechos suben por peldaño y el rumor no; manda la oficial; solo cuentan hechos conocidos antes del momento; todo `sin_calibrar`; sin campos de salud; el informe es determinista y no conoce el partido que estima; la lectura de la hoja (`prefer_sheet`) no cambia `player-engine-v1`; interruptor y trabajo del worker.
- **Aislamiento**: el único importador nuevo de `fbi.players` es `fbi/shadowjobs/lineup_estimate.py`; el paquete solo alcanza además la regla pura de IA-091.
- **Integración** (PostgreSQL local): E1 guarda los dos equipos una vez (28 jugadores), una baja del proveedor queda `baja_confirmada` con 0; E4 lee la oficial cuando ya estaba; fuera de las ventanas o tras el saque no se estima nada; la tabla rechaza UPDATE/DELETE; `intel.decisions` no se mueve; el comando de medición no escribe nada. Migración 0151: sube, rechaza filas ilegales y baja limpia.

## 5. Cómo se activa en sombra (tras desplegar)

1. Migración **0151** aplicada (el despliegue la aplica).
2. `FBI_LINEUP_ESTIMATE=shadow` en el entorno del worker y reiniciarlo. Opcional: `FBI_LINEUP_ESTIMATE_MINUTES` (1–10, 5 por omisión).
3. Medir (solo lectura, dentro de la imagen del worker): `python -m scripts.ia_players lineups --from AAAA-MM-DD --to AAAA-MM-DD` (JSON). Con 30 días de todas las competiciones carga del orden de 450.000 filas: mejor en horas tranquilas.

## 6. Cómo se apaga y se revierte

`FBI_LINEUP_ESTIMATE=off` y reiniciar: el trabajo ni se programa. Los consumidores (cuando existan) vuelven a la última alineación conocida. Las filas se conservan; bajar la migración borra la tabla.

## 7. Lo pendiente

- Enlazar por nombre los 4.430 hechos «titular» sin id (con `name-match-v2`, IA-088, o con la clave de jugador de IA-071 cuando esté desplegada) y medir entonces los factores por peldaño.
- Selecciones: usar las convocatorias (IA-092) como lista de candidatos.
- Que firmes, competición por competición, el sello `calibrada` donde la medición lo sostenga.
- Decidir si se corrige `player-engine-v1` para leer al titular de la hoja (afecta a sus props en sombra).
