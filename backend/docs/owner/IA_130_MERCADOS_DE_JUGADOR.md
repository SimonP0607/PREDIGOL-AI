# IA-130 · Mercados de jugador en evaluación privada (AD-E04)

Pieza AD-E04 del plan (responsables: IA + Cuotas + Modelos). **Apagada**: tu decisión n.º 7 dice que los mercados de jugador esperan a que la evaluación por alineaciones (E3) sea fiable, y hoy **no hay veredicto de E3** en el tablero de validación (AD-K02). Nada llega al lector, a un pick ni a una decisión.

## 1. Qué hay

- **Cuotas** (`fbi/playermarkets/quotes.py`): lee de las respuestas `/odds` ya guardadas en RAW (no se pide nada nuevo al proveedor) los tiros de jugador (apuestas 240 local y 241 visitante) y los tiros a puerta (269, solo local) con los lectores validados del explorador (`tax-v3`). Cada selección («Jugador – N», al menos N) lleva cuántas casas la cotizan y la marca **«una sola casa»**. Los tiros a puerta del visitante **no tienen precio legible**: la apuesta 275 trae en realidad los goles de cabeza y la taxonomía la oculta; se cuenta, no se rellena. El nombre se empareja con un solo jugador de la hoja de su equipo; si encajan dos o ninguno, queda «sin resolver».
- **Liquidación** (`fbi/playermarkets/settle.py`, regla `player_count_ft@v1`): gana si llega a N; **anulada si no jugó** (no está en la hoja o 0 minutos), como suelen hacer las casas; un minuto ya es jugar; si jugó pero falta su cifra, **no se liquida** (nunca cuenta como perdida); prórroga o partido sin estadísticas, no se liquida; partido cancelado o sin resultado a las 72 h, anulada (como `settle-v4`).
- **Estados** (`fbi/playermarkets/admission.py`): apagada mientras E3 no sea fiable; antes de la oficial, siempre **pendiente de alineaciones**; si llega el saque sin oficial, **descartada**; con una sola casa nunca se confirma por precio (hace falta 3). Una prueba recorre todas las combinaciones: **0 selecciones confirmadas sin alineación oficial**.

## 2. Qué no se hizo y por qué

- **No se añadió la regla a `market/rules.py`** (lo pedía la ficha): ese registro es de reglas de partido que leen columnas de `market.fixture_outcomes` y se sincronizan a `market.settlement_rules`, y es zona de Cuotas. La regla de jugador vive en su propio módulo, con versión, hasta que Cuotas decida.
- **No se extraen las cuotas de jugador a `market.odds_quotes`** ni se crea tabla: cambiar el extractor es de Cuotas y escribiría en producción. Las cuotas siguen en RAW (nunca se borra) y se leen bajo demanda.
- **Sin familias en `decision-v2`**: la puerta de E3 está cerrada; entran, en sombra, cuando cambie `E3_RELIABLE` (y `LINEUP_EVALUATION_RELIABLE` del catálogo, que una prueba mantiene iguales) tras un veredicto de E3.

## 3. Medición

`python -m scripts.ia_player_markets measure --from AAAA-MM-DD --to AAAA-MM-DD` (solo lectura): partidos con precio de tiros de jugador, casas por selección, cuota de «una sola casa», nombres resueltos, liquidación y estados — la **muestra registrada para AD-K02**. Desde esta sesión no hubo acceso a producción; la referencia medida es el catálogo de mercados del 17-nov-2026 (14 días): tiros de jugador local y visitante en **58 partidos**, tiros a puerta local en **13**, siempre **1 casa** en la mediana.

## 4. Apagar o revertir

No hay nada encendido. `FBI_PLAYER_MARKETS=shadow` no abre nada por sí solo mientras E3 no sea fiable. Revertir el commit quita el módulo; no hay tabla ni migración propia.
