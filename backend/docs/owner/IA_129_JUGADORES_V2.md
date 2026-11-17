# IA-129 · Jugadores: minutos esperados × tasa × titularidad (`player-engine-v2`, AD-B08)

Pieza AD-B08 del plan de la arquitectura definitiva 2026 (responsable: Modelos). **Todo en sombra**: nada llega al lector, a un pick, a `decision-v1` ni a `decision-v2`; `FBI_PICKS_SOURCE` sigue apagado; nada se entrena ni se promociona solo; ningún modelo de lenguaje calcula una cifra.

## 1. Qué hace

Cada mercado de jugador (goles, asistencias, tiros, tiros a puerta, faltas, tarjeta, atajadas del portero) se calcula como

> **minutos esperados × tasa por 90 (con su muestra) × probabilidad de ser titular**

y **nunca se suponen 90 minutos seguros**: los minutos si es titular son la media ponderada de sus últimas titularidades (un jugador que juega una hora cuando sale de inicio se calcula con una hora). La probabilidad de titular, de entrar desde el banquillo y los minutos los pone la **titularidad estimada** de AD-D04 (`lineup-estimate-v1`, IA-094: minutos recientes, bajas confirmadas, hechos «titular» con su peldaño y la hoja oficial cuando ya está leída), no el modelo propio de v1. Las tasas, el modelo de conteo (binomial negativa) y la mezcla «titular / suplente / no juega» son las de `player-engine-v1`, sin cambios.

Ejemplo del Doc 1, calculado por el propio código (prueba `test_doc1_example…`): 1,0 tiros a puerta por 90 da un **63 %** de al menos uno en 90 minutos; con un 85 % de ser titular, **53 %**.

Reglas comprobadas por pruebas: con titularidad 0 (y sin opción de entrar) la probabilidad es **0**; con la alineación oficial leída la titularidad es **0 o 1**; las previsiones se **reconstruyen idénticas** con los datos de su momento (lo que pasó después no cambia nada); cada cifra lleva su muestra (`nineties`: unidades de 90 minutos propias detrás de la tasa; `start_sample`: partidos del equipo detrás de la titularidad) y el sello `sin_calibrar`.

**Nota sobre los titulares del proveedor (hecho medido en IA-094, 17-nov-2026, 4.575 lados):** las estadísticas del proveedor marcan **14,47 titulares por equipo** frente a **10,79** en las actas oficiales (`is_substitute` vale «falso» para quien entró desde el banquillo). v2 lee al titular **de la hoja** (como la titularidad estimada); `player-engine-v1` queda exactamente como estaba.

## 2. Qué se guarda (migración 0163, solo añadido)

`intel.player_forecasts`: una fila por jugador, mercado, línea, partido y evaluación (**E1**, T-24 a T-12 h; **E4**, T-20 a T-10 min): probabilidad de superar la línea (sin condición y «si juega», que es como liquida la casa), media, probabilidad de titular y de entrar, minutos si es titular y si entra, minutos esperados, tasa por 90 (la suya, la previa y el factor del rival) con su muestra, dispersión, base y muestra de la titularidad, si la oficial estaba leída, sello, versiones (`player-engine-v2`, `lineup-estimate-v1`) y momento. La base rechaza una previsión posterior al saque, una probabilidad mayor que 0 para quien no puede jugar, una hoja oficial que no sea 0 o 1 y una línea entera. `UPDATE` y `DELETE` rechazados. Solo estados de disponibilidad: **ningún dato médico**.

El trabajo `player_forecast_shadow` **nace apagado** (`FBI_PLAYER_ENGINE_V2=off`). En `shadow`, cada 5 minutos (`FBI_PLAYER_ENGINE_V2_MINUTES`) calcula como mucho 8 partidos seguidos en su ventana. Sin proveedor, sin modelo de lenguaje.

## 3. Evaluación (backtest walk-forward)

`python -m scripts.ia_players evaluate-v2 --from AAAA-MM-DD --to AAAA-MM-DD [--competition N]` (solo lectura): cada candidato se pronostica **90 minutos antes del saque**, antes de la alineación, con lo conocido entonces; la probabilidad sin condición se compara con el conteo real (0 si no jugó) y con la **base ingenua de v1 hecha incondicional** (proporción de candidatos que fueron titulares × frecuencia del evento entre los titulares de su puesto). Por mercado y línea: n, eventos, log loss y Brier de ambos, diferencia pareada con su error, y veredicto **MEJORA** (el IC 95 % de la diferencia queda por debajo de 0), **NO_MEJORA** o **INSUFICIENTE** (menos de 2.000 pronósticos con resultado o de 200 eventos en la línea principal). Un veredicto **no activa nada**: todas las familias siguen en sombra.

**Estado de la medición:** desde esta sesión no hubo acceso de lectura a producción, así que **no hay veredictos medidos todavía**. Se miden con el comando de arriba en el servidor (solo lectura).

## 4. Protocolo E6 (`proto-int-a08-v1`), sin cambios

El protocolo sigue con su huella y su parada preregistrada (una sola evaluación: el primer día en que la ejecución en seco muestre 1.500 partidos en los dos segmentos, o el 31-mar-2027). Nuevo: `python -m scripts.ia_players e6` hace esa **ejecución en seco** (no lee ningún marcador) y da una **cota superior** por segmento; con menos de 1.500 el estado es seguro **PENDIENTE POR MUESTRA** (el 11-nov había unos 475 y 2.120). Si la cota llega a 1.500 en los dos, dice **RECUENTO_COMPLETO** (falta comprobar dos exclusiones —predicción del modelo actual y consenso del mercado en T90— antes de evaluar), nunca «evaluar».

## 5. Cómo se apaga o se revierte

- Apagar: `FBI_PLAYER_ENGINE_V2=off` (o quitar la variable). Volver a `player-engine-v1` es no usar v2: v1 no cambió.
- Revertir el código: revertir el commit. La tabla se conserva (solo añadido); la migración 0163 se puede deshacer y solo borra esa tabla.
