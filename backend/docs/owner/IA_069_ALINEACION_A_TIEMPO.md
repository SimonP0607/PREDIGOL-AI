# IA-069 · Alineación oficial a tiempo (pieza AD-D05)

Pieza AD-D05 del plan de la arquitectura definitiva 2026. Guarda la hora a la que llega cada alineación oficial, que hasta
ahora se perdía, y añade un sondeo previo al partido que **nace apagado** y, encendido, funciona **solo en sombra**. No
cambia lo que ve el lector, ni los agentes, ni los picks, ni `decision-v1`.

## 1. El problema

`core.fixture_lineups` guarda la última versión de la alineación de cada equipo. Cada lectura reescribe `fetched_at`, así que
la hora de la primera llegada desaparece en cuanto se vuelve a leer. Sin esa hora no se puede saber qué sabía el sistema en
cada momento antes del saque, ni cuánto antes llega la alineación en cada competición, ni si se corrigió un titular.

Hoy se lee así:

- la lectura previa (`prematch_lineups`) pregunta cada 10 minutos en los últimos 75 y se para en cuanto tiene los dos
  equipos;
- el seguimiento en vivo empieza 2 minutos antes del saque.

Por eso la llegada solo se conoce con 10 minutos de precisión, y un titular corregido después de la primera lectura no se ve
hasta el seguimiento. Según la medición anterior (B05, 16-nov-2026, 3.401 partidos de 30 días), la alineación llega a unos
20 minutos del saque en la mediana, y el 76 % de los partidos la tiene antes de empezar (84 % en ligas, 29 % en copas).

## 2. Qué cambia

**Migración `0140_lineup_first_seen`.** Va encadenada sobre `0137`; el número puede cambiar si se fusiona otra antes. Hace
dos cosas.

1. **`core.fixture_lineups.first_seen_at`.** Es la hora de la respuesta del proveedor que escribió la fila por primera vez.
   La pone la propia base de datos al insertar y no se cambia nunca más: un disparador devuelve el valor guardado aunque una
   actualización diga otra cosa. Así vale para todos los que escriben alineaciones (el seguimiento en vivo, la lectura previa,
   las lecturas de después del partido, la carga histórica y el reprocesado). Las filas que ya existían quedan en blanco
   (NULL), porque su primera llegada ya se había perdido y no se inventa.
2. **`core.fixture_lineup_arrivals`.** Es una tabla de solo añadido: no admite cambios ni borrados. Recibe una fila cada vez que
   la alineación de un equipo llega con un contenido distinto del de la vez anterior (formación, entrenador, jugadores, dorsales,
   posiciones o titulares). Un reenvío idéntico no añade nada, y una corrección de un titular añade una fila. La columna
   `channel` dice quién la vio: los escritores de detalle de siempre (`detail_writer`) o el sondeo nuevo (`lineup_watch`). Solo
   se guardan observaciones hasta 30 horas después del saque, para que la carga histórica de temporadas viejas no cuente como
   «llegada».

Con esto, los escritores de detalle (`fbi/ingestion/details.py`) anotan la llegada en cada lectura. Es una consulta pequeña
por equipo y no cambia nada de lo que ya escribían.

**Sondeo `lineup_watch` (`fbi/ingestion/lineup_watch.py`).** Está apagado por defecto. En sombra, cada 3 minutos pregunta por
los partidos seguidos que empiezan en los próximos 90, con una petición `/fixtures?ids=` por cada 20 partidos (la misma que
usa el seguimiento en vivo). Las alineaciones que lee se guardan solo como llegadas (`channel = 'lineup_watch'`). **No escribe
nada más**: ni la alineación, ni el partido, ni el estado en vivo, ni el detalle. Las respuestas van a RAW y al índice de
respuestas, como cualquier otra petición. Corre en su propio bucle, fuera del planificador (lección de AD-A05), con un tiempo
máximo de 10 minutos.

**Informe de solo lectura `python -m scripts.ia_lineup_timing [--days 14] [--json]`.** Saca una fila por competición con:

- partidos jugados, cuántos con las dos alineaciones y cuántos con ellas antes del saque;
- los minutos entre la primera vez que se vieron los dos equipos y el saque (mediana, p10 y p90);
- cuántas vio antes el sondeo;
- cuántas tuvieron un titular cambiado antes del saque;
- una marca de «muestra pequeña» si hay menos de 10 partidos;
- la comprobación de cierre: cuántas filas de alineación tienen `first_seen_at`.

La «publicación en el proveedor» es la primera vez que una de nuestras lecturas la vio. La publicación real es anterior, como
mucho, en el intervalo entre lecturas: 3 minutos si la vio primero el sondeo y hasta 10 minutos si fue la lectura previa. **La
publicación oficial** (la de la competición o el club) **no se compara**, porque todavía no hay ninguna fuente permitida que la
feche (AD-C02). La columna existe, está vacía y el informe lo dice.

## 3. Interruptores

| Variable | Por defecto | Qué hace |
| --- | --- | --- |
| `FBI_LINEUP_WATCH` | `off` | `off` o `shadow`. Cualquier otra palabra cuenta como `off`. Apagado, el worker ni siquiera programa el trabajo. |
| `FBI_LINEUP_WATCH_MINUTES` | `3` | Cada cuántos minutos se pregunta (de 1 a 30). |
| `FBI_LINEUP_WATCH_DAILY_BUDGET` | `1200` | El máximo de peticiones del sondeo en un día UTC (de 1 a 6.000). |
| `FBI_LINEUP_WATCH_RESERVE` | `6000` | No pregunta si quedan menos de esta reserva más las ventanas de captura de las próximas 24 h, ni en nuestro presupuesto ni en lo que dice el proveedor. |
| `FBI_LINEUP_WATCH_PER_RUN` | `8` | El máximo de peticiones en cada pasada (8 × 20 = 160 partidos). |

Un número que no se entiende o que está fuera de rango vuelve a su valor por defecto. Una errata nunca enciende el sondeo ni
amplía su presupuesto. Si en una pasada no se puede preguntar por todos los partidos, se pregunta primero por los que empiezan
antes. La pasada también se para en mitad si las cabeceras del proveedor dicen que lo que queda baja de la reserva.

## 4. Cuánto cuesta (medición en producción, solo lectura, 16-nov-2026 a las 23:00 UTC)

| Dato | Valor | De dónde sale |
| --- | --- | --- |
| Partidos seguidos por día UTC (30 días completos, 17-oct a 15-nov; 3.454 partidos) | mediana 78,5, media 115,1, p90 272, máximo 323 | `core.fixtures` de competiciones con `is_tracked` (136), estados terminado, en vivo o programado |
| Peticiones al día del sondeo cada 3 minutos, de T-90 al saque, en lotes de 20 (simulado sobre esos 30 días) | media 423, p90 701, máximo 752 | la misma tabla, contando cada 3 minutos los partidos que empiezan en los 90 siguientes |
| Lo mismo cada 5 minutos | media 254, p90 421, máximo 451 | ídem |
| Lo mismo con una petición por partido (sin lotes), cada 3 minutos | media 3.452, máximo 9.813 | ídem (por eso se pregunta en lotes) |
| Partidos en la ventana de 90 minutos a la vez, como máximo | 122 (7 peticiones) | ídem |
| Gasto diario de API-Football (14 días, 2 a 15-nov) | media 16.156, mediana 15.046, máximo 23.430, sobre un presupuesto de 60.000 | `raw.provider_quota` |
| Lectura previa actual (`prematch_lineups`), 7 días | entre 47 y 229 peticiones al día | `raw.ingestion_runs` |

Con los valores por defecto, el día más cargado de los 30 costaría 752 peticiones, el **1,3 % del presupuesto de 60.000**, y
un día medio 423 (0,7 %). El techo propio (1.200) queda por encima del peor día medido y por debajo del 2 % del presupuesto.

La ficha estimaba 63 partidos seguidos al día. La medición da más (mediana 78,5, media 115,1) porque los fines de semana pasan
de 250 partidos. Las cifras de coste de arriba ya usan los partidos reales.

## 5. Qué no cambia

- Lo que lee el producto: la alineación de `core.fixture_lineups` (salvo la columna nueva, que nadie lee todavía), el
  partido, el estado en vivo, el centro del partido, los agentes, los paquetes, `decision-v1`, los picks y la liquidación.
- La lectura previa de 10 minutos y el seguimiento en vivo siguen igual.
- Ningún proveedor nuevo, ningún modelo de lenguaje y ninguna probabilidad.

## 6. Cómo se enciende en sombra (paso en el servidor, cuando el dueño lo decida)

1. Tras desplegar, comprueba que la migración está aplicada: `alembic current` debe decir `0140` o una posterior.
2. Añade `FBI_LINEUP_WATCH=shadow` al entorno del worker y reinícialo como siempre. En el registro aparece el trabajo
   `lineup_watch`, en lugar de `worker.lineup_watch_off`.
3. Al cabo de un día, mira el informe: `python -m scripts.ia_lineup_timing --days 1`. Mira también el gasto en
   `raw.ingestion_runs` (`job_type = 'lineup_watch'`).

## 7. Cómo se apaga o se revierte

- **Apagar:** `FBI_LINEUP_WATCH=off` (o quitar la variable) y reiniciar el worker. Las filas guardadas se quedan.
- **Revertir el código:** la anotación de llegadas en `details.py` es una sola llamada; quitarla no afecta a nada más.
- **Revertir la migración** (`alembic downgrade 0137`): quita la columna, el disparador y la tabla de llegadas, y con ellos
  las horas medidas. No es necesario para apagar nada.

## 8. Riesgos y límites

- Cada lectura de alineación hace una consulta más por equipo, en la misma transacción. Si fallara, fallaría el lote de
  20 partidos, como cualquier otro fallo de datos del seguimiento. La consulta usa su propio índice.
- Las filas que ya existían quedan sin `first_seen_at`. La comprobación de cierre debe medirse con partidos posteriores al
  despliegue.
- La hora de llegada es la hora de la respuesta tal como la guarda el índice de RAW. Si dos lecturas devuelven exactamente la
  misma respuesta, cuenta la primera, que es la correcta.
- El sondeo guarda sus respuestas en RAW: unas 400 a 750 respuestas pequeñas al día.
