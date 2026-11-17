# IA-070 · Catálogo de mercados con estado

Pieza AD-E01 del plan maestro de la arquitectura definitiva 2026 (ola 2). Aplica tu decisión n.º 7: córners y tarjetas primero,
se conservan los mercados que ya se pueden evaluar, los de jugador solo cuando la evaluación por alineaciones sea fiable, y **ningún
mercado se ofrece sin datos, cuotas y una regla de liquidación que se pueda comprobar**.

**Qué no cambia:** nada de lo que ve el lector, ningún pick, `decision-v1`, `FBI_PICKS_SOURCE` (sigue apagado), umbrales,
probabilidades, prompts ni la sombra. No hay migración, ni interruptor, ni tarea nueva en el worker. Hoy nadie lee el estado: lo
leerán los contratos C-01 (Partido) y C-02 (Selección) cuando se construyan, y solo en la proyección privada hasta AD-J03.

## 1. Qué hace

Cada mercado que el proveedor cotiza recibe **uno de cuatro estados**, con **un motivo** de una lista cerrada:

| Estado | Qué significa | Motivos posibles |
| --- | --- | --- |
| `evaluable` | Regla de liquidación, resultados para liquidarla, precio de 3 casas o más, un modelo con pronósticos y un calibrador **validado** (campeón de `calib-gate-v1`) | `completo` |
| `en_calibracion` | Todo lo anterior menos el calibrador validado | `sin_calibrador_validado` |
| `necesita_datos` | Podría evaluarse, pero falta una pieza medible | `menos_de_3_casas`, `liquidacion_sin_muestra`, `pendiente_alineaciones`, `sin_modelo` |
| `no_ofrecer` | No se evalúa nunca en este estado | `fuera_de_alcance`, `sin_regla_liquidacion`, `regla_no_registrada`, `sin_cuotas`, `sin_datos_de_resultado`, `fuera_del_catalogo` |

«Evaluable» **no** quiere decir «tiene ventaja»: la ventaja es el veredicto de AD-K02, y hoy ningún mercado la tiene validada
(`intel.promotions`: la última fila `market_edge` de cada mercado y modelo dice `NOT_VALIDATED`).

**Las reglas van en orden fijo y la primera que falla decide** (versión `market-states-v1`, en `backend/src/fbi/api/services/market_status.py`):

1. Familia fuera del plan (momento del partido, especiales, «pasa de ronda», otros deportes, sin clasificar) → `no_ofrecer · fuera_de_alcance`.
2. Sin regla de liquidación que se pueda aplicar (`fbi/market/rules.py`) → `no_ofrecer · sin_regla_liquidacion`.
3. La regla no está registrada en `market.settlement_rules` → `no_ofrecer · regla_no_registrada`.
4. Ninguna cuota en los últimos 14 días → `no_ofrecer · sin_cuotas`.
5. De los partidos con precio ya jugados (al menos 30), menos de la mitad tiene el dato que la regla lee → `no_ofrecer · sin_datos_de_resultado` (la frontera del 50 % es la de la TESIS §E).
6. Menos de 3 casas en la mediana de los partidos con precio → `necesita_datos · menos_de_3_casas` («una sola casa» nunca es evaluable).
7. Menos de 30 partidos con precio ya jugados → `necesita_datos · liquidacion_sin_muestra`.
8. Mercado de jugador o portero mientras la evaluación por alineaciones no sea fiable → `necesita_datos · pendiente_alineaciones`.
9. Ningún pronóstico del mercado en 14 días (`models.predictions`, `models.match_forecasts`) → `necesita_datos · sin_modelo`.
10. Ningún calibrador campeón en vigor → `en_calibracion · sin_calibrador_validado`.
11. Si pasa todo → `evaluable · completo`.

Un partido con precio cuyo resultado no trae el dato (por ejemplo, córners sin estadística) se liquida como «sin resultado», nunca
como pérdida, y sale de la muestra. Por eso el estado viaja con su porcentaje liquidable (`settleable_pct`): el hueco se ve.

La unidad es la clave del catálogo (`market.markets`: `CORNERS_OU`, `OU_1H`…; los cinco clásicos conservan la suya), que junta las
apuestas del proveedor que son el mismo mercado (307 y 339, doble oportunidad de córners). Una apuesta sin clave (jugadores, córners por
mitad, hándicaps sin mapear…) es su propio mercado, `bet_<id>`.

## 2. Cómo se sirve (sin tabla)

El estado se guarda como **datos versionados en el repositorio**: `backend/src/fbi/api/services/market_states.json`, con la versión del
catálogo, la hora de la medición, las ventanas, los umbrales y, por mercado, los hechos medidos y su estado. Un mercado solo cambia de
estado cuando se mide de nuevo y alguien revisa el cambio (una línea por mercado en el diff). El lector (`load_catalogue`) **vuelve a
juzgar** cada mercado con el código vigente: si mañana se quita una regla de liquidación del código, el mercado baja a `no_ofrecer`
aunque el fichero diga otra cosa. Las pruebas de CI fallan si el fichero y el juicio del código no coinciden, si un mercado del libro no
tiene estado y motivo, o si aparece un `evaluable` sin regla, sin 3 casas o sin calibrador validado.

La ficha pedía una tabla `market.market_states`; el encargo pidió no migrar salvo imprescindible y no lo es: el fichero tiene las mismas
columnas y se puede cargar en una tabla de solo añadido el día que haga falta.

Para los contratos: `MarketCatalogue.status(clave)`, `.for_bet(id_del_proveedor)`, `.for_market(clave, apuestas)` (para un mercado de
`/matches/{id}/markets/catalog`) y `.view(clave)`, que devuelve el modelo `MarketStatusView` (ejemplos en
`backend/tests/fixtures/contracts/market_states/`). Una clave desconocida responde `no_ofrecer · fuera_del_catalogo`.

## 3. Estado medido en producción (17-nov-2026 02:30 UTC, solo lectura)

Seis consultas de solo lectura (`fbi.api.services.market_status.queries`), exportadas tal cual en
`backend/docs/owner/lab/IA_070/facts_20261117T0230Z.json`. Ventana de precios: capturas de los 14 días anteriores, **1.185 partidos con
precio**. Las 338 definiciones de la base coinciden con la taxonomía del código (0 diferencias).

**337 mercados: 4 evaluables, 20 en calibración, 18 necesitan datos, 295 no ofrecer** (de estos, 283 son apuestas del proveedor
cuyas cuotas no se extraen al libro).

| Estado | Mercados | Lo que hay detrás |
| --- | --- | --- |
| Evaluable | 1X2, más/menos (OU), ambos marcan (BTTS), hándicap asiático (AH) | 7–10 casas de mediana; 100 % liquidable; calibrador campeón (poisson, dixon_coles y, en 1X2, elo_ologit) |
| En calibración | **Doble oportunidad (DC)**; córners más/menos, 1X2 y por equipo; tarjetas más/menos; goles por mitad (1X2, más/menos, ambos marcan, doble oportunidad, más/menos por equipo y mitad), mitad con más goles, HT/FT | Modelo con pronósticos (722–838 partidos en 14 días) y 3 o más casas, sin calibrador validado |
| Necesita datos | Tarjetas por equipo (2 casas); doble oportunidad de córners (1 casa); hándicap asiático 2.ª mitad (2); sin empate por mitad y mitad con más goles por equipo (1); remates y tiros a puerta de equipo, total y 1X2 (1 casa); goles por equipo, empate no acción, hándicap asiático 1.ª mitad, par/impar por mitad (sin modelo) | |
| No ofrecer | Amarillas (7 claves) y rojas: 0 cuotas; remates y tiros a puerta por equipo local/visitante: 0 cuotas; jugadores (47 apuestas), córners por mitad y hándicaps sin mapear: sin regla de liquidación; momento del partido, especiales, otros deportes, «pasa de ronda»: fuera de alcance | |

Cifras de las familias prioritarias (decisión n.º 7):

| Mercado | Partidos con precio | Casas (mediana) | Con 3+ casas | Jugados | Liquidables | Pronósticos 14 d |
| --- | --- | --- | --- | --- | --- | --- |
| `CORNERS_OU` | 1.080 de 1.185 (91,1 %) | 5 | 984 | 1.016 | 833 (82,0 %) | 724 |
| `CORNERS_1X2` | 959 | 4 | 756 | 899 | 785 (87,3 %) | 726 |
| `CARDS_OU` | 437 (36,9 %) | 3 | 241 | 409 | 409 (100 %) | 764 |
| `CARDS_OU_HOME` / `_AWAY` | 435 | 2 | 0 | 408 | 408 | 760 / 764 |

**Diferencias con lo que esperaba la ficha** (manda la medición, no la ficha):
- **Doble oportunidad no es evaluable hoy, está en calibración**: tiene 171 ajustes en `intel.calibrators`, pero ninguno pasó
  `calib-gate-v1` (el 13, 15 y 16-nov quedó como `CHALLENGER` por muestra fuera de muestra insuficiente, `n_oos`). La ficha decía «cinco
  clásicos evaluables»; son cuatro.
- **Jugadores salen `no_ofrecer`, no `necesita_datos`**: no tienen regla de liquidación (la ficha pide que «sin regla → no ofrecer» sea
  una prueba) y la decisión n.º 7 dice lo mismo. Cuando AD-E04 escriba su regla pasarán a `necesita_datos · pendiente_alineaciones` y
  solo saldrán de ahí con un cambio revisado de `LINEUP_EVALUATION_RELIABLE` (nueva versión del catálogo).
- **Córners: el 18 % de los partidos con precio ya jugados no tiene córners en el resultado** (833 de 1.016). No impide calibrar, pero
  la muestra de AD-E03 será ese 82 %.
- Tarjetas: precio en el 36,9 % de los partidos con precio en 14 días (el registro del 9-nov decía 42,7 % sobre 825 partidos; otra
  ventana).

## 4. Cómo se mide de nuevo

Dentro del contenedor del worker (conexión de solo lectura, 95 s por consulta; no escribe en la base):

```
python -m scripts.ia_market_states report            # tabla de estados y motivos
python -m scripts.ia_market_states report --json     # todo, en JSON
python -m scripts.ia_market_states snapshot --out src/fbi/api/services/market_states.json   # en una copia del repo, para revisar y fusionar
python -m scripts.ia_market_states check             # el fichero vigente juzgado de nuevo: 0 sin diferencias, 1 con diferencias
```

## 5. Cómo se apaga o se revierte

No hay nada encendido: nadie lee el estado todavía. Si un contrato ya lo leyera, se deja de leer (`load_catalogue`) y nada más cambia;
el fichero y sus versiones anteriores quedan en el historial del repositorio. Revertir el PR quita el módulo, el script, el fichero y
las pruebas sin tocar la base.
