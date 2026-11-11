# IA-039 — E4: tiros y xG en los ratings (LAB)

*Plan Maestro de Evolución de PrediGol Intelligence 2026, pieza INT-A09, ola 1. Protocolo proto-int-a09-v1, huella 400778f8…; ejecutado el 11-nov-2026.*

**Resumen.** El veredicto es **RECHAZA** en los dos segmentos que se pudieron evaluar: el resto de ligas, con 2.738 partidos fuera de muestra repartidos en 39 días.

- **1X2.** El retador no mejora al modelo actual. Su log loss es +0,0061 más alto (IC95: −0,0007 a +0,0127). Además, su peso frente al mercado es negativo con todo el intervalo por debajo de cero: −0,38 (IC95: −0,63 a −0,16). Es decir, mezclado con el mercado empeora el pronóstico.
- **Más/menos 2,5.** El retador sí mejora al modelo actual: −0,0094 de log loss (IC95: −0,0140 a −0,0053). Pero no aporta nada que el mercado no tenga: su peso es 0,07 (IC95: −0,19 a +0,33).
- **Ligas prioritarias.** Quedan **PENDIENTES POR MUESTRA**: hay 281 partidos y el protocolo exige 1.500.

La auditoría de fugas sale limpia. Según el protocolo, el retador se archiva con su motivo y el modelo activo no cambia. En producción no se tocó nada.

## Protocolo (sello completo)

Este es el sello que lleva el resultado, tal como lo imprime `ia_lab_e4_xg.py`:

```json
{"protocol": "INT-A09", "version": "proto-int-a09-v1",
 "fingerprint": "400778f85de7acdfc59b1d9e265d7f4c4d5fe42abc4abf71cb5785b33604bd36",
 "framework": "lab-protocol-v1", "registered_on": "2026-11-11", "seed": 20261111,
 "checked_against": "texto canónico incrustado (fbi.research.protocol no está en este entorno)"}
```

**Registro y verificación de la huella**
- El protocolo es `fbi.research.protocol.A09`. Se registró en el commit 1d8c98d (PR #236) antes de mirar ningún resultado.
- Recalculé la huella desde `backend/src/fbi/research/protocol.py`: es el SHA-256 del JSON canónico. Coincide con la fijada en `tests/unit/test_research_protocols.py`.
- La imagen desplegada (`predigol-backend:5ae050a9c56a`) todavía no trae ese módulo. Por eso el script incrusta el texto canónico, recalcula su SHA-256 y se niega a correr si no coincide con la huella.

**Lo que fija el protocolo**
- **Pregunta.** ¿Unos ratings de ataque y defensa con tiros, tiros a puerta y xG de partidos anteriores pronostican los goles mejor que el modelo actual, y aportan algo que el mercado no tiene?
- **Métrica primaria.** Diferencia pareada del log loss 1X2 (retador menos actual), con IC95 por bootstrap de días. Además, el peso *w* del retador frente al mercado en el pool `p ∝ q^(1−w)·m^w` de `fbi.research.blend`, con su IC95 por bootstrap de días.
- **Regla para PASAR.** En al menos un segmento preregistrado deben cumplirse tres cosas: el límite superior del IC de la diferencia es menor que 0, el límite inferior del IC del peso es mayor que 0 y la auditoría de fugas sale limpia. Si falla cualquiera, el resultado es RECHAZA.
- **Muestra mínima.** 1.500 partidos fuera de muestra por segmento; con menos, «pendiente por muestra».
- **Exclusiones.** Equipos con menos de 5 partidos previos con estadísticas, y partidos sin resultado o sin consenso de mercado.
- **Parada.** Una sola evaluación.
- **Segmentos.** Ligas prioritarias (Champions y cinco grandes), resto de ligas con estadísticas, y mercados 1X2 y más/menos 2,5.

**Concreciones que el protocolo deja abiertas, fijadas antes de calcular ninguna métrica**

| Punto | Decisión |
| --- | --- |
| Modelo actual | `poisson`, de la familia `goals`. Motivos: ninguna `model_versions` tiene estado `champion`; `poisson` es el modelo de goles que el producto usa en más/menos 2,5 y tiene calibrador CAMPEÓN en 1X2 y en más/menos. Se usa su `p_raw` en tiempo real (`backtest_session_id IS NULL`), que en los modelos de goles es igual a `p_calibrated`. `dixon_coles` y `elo_ologit` se incluyen solo como contexto. |
| Momento de decisión T | T = saque − 3 h. Del modelo, su última predicción con `data_cutoff_ts` y `created_at` anteriores o iguales a T. Del mercado, el consenso Shin (`devig_method='shin'`) más reciente con T − 6 h ≤ `as_of` ≤ T y el mercado completo. |
| Día y «terminado» | El día es el día de Bogotá (UTC−5). Un partido cuenta como terminado a las 3 h de su saque, la misma regla que `known_before`. Se excluyen los partidos en cuarentena de la validación histórica. |
| Celdas | Grupo de ligas × mercado, cuatro celdas. La regla de PASA se aplica a cada una. Ligas prioritarias: ids 2, 39, 140, 135, 78 y 61. |
| Retador `e4-xg-ratings-v1` | El proceso de cada partido es el xG del proveedor cuando lo tienen los dos lados. Si falta, se usa un xG aproximado = a·(tiros a puerta) + b·(resto de tiros), con *a* y *b* ajustados por mínimos cuadrados solo con partidos anteriores al 1-mar-2026. El objetivo es y = β·goles + (1−β)·proceso. Ataque y defensa se estiman por competición y ajustados por rival, con el punto fijo ponderado de Poisson (ajuste proporcional iterativo), k pseudo-partidos de encogimiento y pesos exp(−ln2·edad/H). λ local = goles medios del local × ataque × defensa rival. De λ local y visitante se saca un Poisson de 0 a 10 goles, y de ahí 1X2 y más/menos 2,5. La historia del día D son los partidos de 730 días cuyo saque + 3 h es anterior o igual al inicio de D. |
| Hiperparámetros | Rejilla H ∈ {90, 180, 365} × β ∈ {0; 0,3; 0,6} × k ∈ {3, 8}. Para cada día D se elige el punto con menor log loss (1X2 + más/menos) del propio retador en los 56 días anteriores a D, dentro de las 101 competiciones donde predijo el modelo actual. |
| Bootstrap | Los bloques son días. La diferencia usa 2.000 remuestreos, con la regla de `fbi.models.metrics.block_bootstrap_ci`. El peso usa 500, con `fbi.research.blend.weight_interval` del paquete instalado. Semilla 20261111 en ambos. |

## Datos y auditoría

### Dónde guarda PrediGol las estadísticas
- **Tabla.** `core.fixture_team_stats`: una fila por partido, lado y fuente. Tiene 17 columnas, entre ellas `shots`, `shots_on_target`, `shots_inside_box` y `expected_goals NUMERIC(6,3)`. NULL significa que el proveedor no lo publicó.
- **Escritura.** La hace `fbi/ingestion/details.py` a partir del bloque `statistics` de API-Football `/fixtures?ids=`, que se interpreta en `fbi/providers/api_football/details.py`.
- **Tablas relacionadas.** La presencia del bloque por partido está en `core.fixture_detail_coverage`; los indicadores de cobertura del proveedor, en `raw.league_coverage`.
- **Volumen** (consulta `consultas/q2.sh`, 11-nov).
  - API-Football: 348.780 filas de 174.390 partidos. Tiros en 313.396 filas; xG en 74.258 filas.
  - football-data.co.uk: 10.658 filas de 5.329 partidos, con tiros y tiros a puerta pero sin xG.
- **Uso actual.** Ningún modelo lee `expected_goals`. `fbi/features/data.py::load_team_stats` lee solo tiros y tiros a puerta, que alimentan las cuotas de tiros de `mnlogit` y `hgb`. Los modelos de goles (`poisson`, `dixon_coles`) solo usan goles.

### Cobertura de las estadísticas

Partidos terminados con marcador, contando solo los que tienen el dato de los dos lados. La temporada es la etiqueta del proveedor.

| Temporada | Terminados | Con tiros y a puerta | Con xG |
| --- | --- | --- | --- |
| 2018–2021 | 100.592 | 62.855 (62,5 %) | 0 |
| 2022 | 27.695 | 18.503 (66,8 %) | 1.119 (4,0 %) |
| 2023 | 27.281 | 21.413 (78,5 %) | 6.955 (25,5 %) |
| 2024 | 27.337 | 21.352 (78,1 %) | 8.641 (31,6 %) |
| 2025 | 27.268 | 20.737 (76,0 %) | 12.938 (47,4 %) |
| 2026 (en curso) | 23.168 | 11.442 (49,4 %) | 7.363 (31,8 %) |

**Ligas prioritarias.** Las cinco grandes tienen tiros en el 100 % de los partidos en todas las temporadas. Su xG está en torno al 50–55 % en 2022 y entre el 99 y el 100 % de 2023 a 2025. En 2026 va del 90,1 % (Bundesliga, 81 partidos) al 100 % (LaLiga y Serie A). La Champions es la excepción:

| Temporada | Tiros | xG |
| --- | --- | --- |
| 2022 | 76,2 % | 13,6 % |
| 2023 | 85,0 % | 58,4 % |
| 2024 | 77,1 % | 67,7 % |
| 2025 | 80,4 % | 67,3 % |
| 2026 (162 partidos) | 69,8 % | 38,3 % |

**Resto de competiciones.** Competición-temporadas con al menos 20 partidos, según la parte con xG:

| Temporada | ≥ 80 % | 20–80 % | 1–20 % | 0 % |
| --- | --- | --- | --- | --- |
| 2025 | 22 | 40 | 14 | 35 |
| 2026 | 35 | 40 | 8 | 28 |

**Ventana de evaluación** (desde el 1-sep-2026, consulta `q3.sh`):
- Resto: 7.251 terminados, 5.189 con tiros de los dos lados y 3.345 con xG (46 %).
- Prioritarias: 475 terminados, los 475 con tiros y 454 con xG (96 %).

### El modelo actual (consultas `q1`, `q4`, `q5`, `q6`)
- **Registro.** `models.model_registry` tiene `poisson` (73 versiones), `dixon_coles` (73) y `elo_ologit` (72), entre otros. Todas las `model_versions` están en `experimental`: ninguna es `champion` ni `shadow`.
- **Campeones de calibración.** El papel de campeón está en los calibradores (`intel.promotions` → CHAMPION, `logit2`). Hay campeones para 1X2, más/menos, ambos marcan y hándicap asiático con `poisson` y `dixon_coles`, y para 1X2 con `elo_ologit`. Se promovieron entre el 4 y el 9 de noviembre.
- **Lo que muestra el producto** (`models.match_forecasts`, últimos 30 días; partidos distintos por modelo y estado de calibración, y un mismo partido puede aparecer en los dos estados):
  - Más/menos 2,5 sale de `poisson`: 2.181 partidos calibrados y 2.369 sin calibrar.
  - 1X2 sale casi siempre de `elo_ologit` (1.625 calibrados y 2.371 sin calibrar). `dixon_coles` aparece en 51 y 104, y `poisson` en 36 sin calibrar.
- **Spec vigente** (`analytics.promoted_forecast_spec`, id 1, del 22-oct): 730 días de historia, ξ = 0,002 por día (vida media de unos 347 días) y penalización 1,0. Se reajusta por competición.
- **Predicciones en tiempo real** guardadas 3 h o más antes del saque, en la ventana: `poisson` 4.059 partidos, `dixon_coles` 4.051 y `elo_ologit` 4.131.
  - La primera es del 25-sep-2026. En ligas prioritarias, la primera es del 6-oct-2026 a las 01:36 UTC.
  - De 32.577 filas, ninguna tiene `created_at` más de 10 minutos después de `data_cutoff_ts`: las predicciones se guardan al momento.

### Extracción y embudo

`extract.sql` se ejecutó el 11-nov-2026 entre las 05:03 y las 05:09 UTC, en solo lectura y con `statement_timeout` de 95 s. `current` y `market` van en 12 tramos semanales porque en una sola sentencia superaban los 95 s.

| CSV | Filas | md5 |
| --- | --- | --- |
| coverage.csv | 1.085 | 54e5ee17d1203b8133510ffc411ea944 |
| matches.csv (desde 1-ene-2024) | 86.587 | 173b8a9fc743f68e10de70ca8ab73627 |
| current.csv | 52.943 | ae9bc01e8f5c87a6f676c93c71dd6d70 |
| market.csv | 19.217 | 741d090237be341d47b93169df8e8d96 |

En `matches.csv`, 61.373 partidos tienen tiros y tiros a puerta de los dos lados (61.372 de API-Football y 1 de football-data), 31.753 tienen xG y 13 están en cuarentena.

Embudo para 1X2. Más/menos 2,5 es igual, salvo un partido más con mercado en el resto (3.365).

| Paso | Prioritarias | Resto |
| --- | --- | --- |
| Terminados con marcador desde el 1-sep (día de Bogotá) | 475 | 7.246 |
| Sin cuarentena | 475 | 7.244 |
| Con predicción del modelo actual ≤ saque − 3 h | 304 | 3.755 |
| … y con consenso Shin de 6 h o menos | 302 | 3.364 |
| … y los dos equipos con ≥ 5 partidos previos con estadísticas | **281** | **2.738** |

### Auditoría de fugas: limpia

| Comprobación | Casos | Violaciones |
| --- | --- | --- |
| Corte del modelo actual ≤ saque − 3 h | 20.351 | 0 |
| `created_at` del modelo actual ≤ saque − 3 h | 20.351 | 0 |
| Mercado: `as_of` ≤ saque − 3 h y antigüedad ≤ 6 h | 7.687 | 0 |
| Historia del retador: saque + 3 h ≤ inicio del día D | 1.581.876 | 0 |
| El partido objetivo no está en su propia historia | 10.040 | 0 |
| Objetivo dentro de su día; historia anterior a su saque | 10.838 / 3.188 | 0 |
| Selección de hiperparámetros solo con días anteriores a D | 143.893 | 0 |
| xG aproximado ajustado antes del walk-forward | 1 | 0 |

Nunca se usa ninguna estadística del propio partido ni posterior a su saque.

## Resultados

Una sola evaluación: 11-nov-2026, entre las 05:32 y las 05:35 UTC, 143 s con 1 CPU. El pool usado es `fbi.research.blend` del paquete instalado.

- **Dif.** es el log loss del retador menos el del modelo actual. Negativo significa que el retador es mejor.
- **DMD** es la diferencia mínima detectable alcanzada, 2,80·s/√días, donde *s* es la desviación típica de la diferencia diaria.
- **w** es el peso del retador frente al mercado.

| Celda | n | Días | LL retador | LL actual | LL mercado | Dif. (IC95) | DMD | w (IC95) | Veredicto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prioritarias · 1X2 | 281 | 27 (9-oct → 8-nov) | 0,9307 | 0,9331 | 0,8995 | −0,0024 (−0,0185; +0,0145) | 0,036 | −0,23 (−0,85; +0,26) | PENDIENTE POR MUESTRA |
| Prioritarias · más/menos 2,5 | 281 | 27 | 0,6610 | 0,6738 | 0,6590 | −0,0128 (−0,0289; +0,0017) | 0,026 | +0,40 (−0,54; +1,13) | PENDIENTE POR MUESTRA |
| Resto · 1X2 | 2.738 | 39 (29-sep → 10-nov) | 0,9966 | 0,9905 | 0,9655 | +0,0061 (−0,0007; +0,0127) | 0,013 | −0,38 (−0,63; −0,16) | RECHAZA |
| Resto · más/menos 2,5 | 2.738 | 39 | 0,6786 | 0,6880 | 0,6695 | −0,0094 (−0,0140; −0,0053) | 0,018 | +0,07 (−0,19; +0,33) | RECHAZA |

**Análisis secundarios y de contexto.** Ninguno cuenta para el veredicto.

**Resto de ligas: historia con xG frente a solo tiros**

| Historia | n | 1X2 | Más/menos 2,5 |
| --- | --- | --- | --- |
| Con xG (≥ 50 % de la historia) | 1.286 | +0,0073 (−0,0005; +0,0145) | −0,0082 (−0,0138; −0,0019) |
| Solo tiros (< 50 % con xG) | 1.452 | +0,0051 (−0,0039; +0,0144) | −0,0105 (−0,0199; −0,0019) |

**El retador frente a otros modelos**

| Comparado con | Celda | n | Dif. (IC95) |
| --- | --- | --- | --- |
| `dixon_coles` | Resto · 1X2 | 2.735 | +0,0049 (−0,0018; +0,0115) |
| `dixon_coles` | Resto · más/menos 2,5 | 2.735 | −0,0094 (−0,0140; −0,0052) |
| `elo_ologit` (el que el producto usa en 1X2) | Resto · 1X2 | 2.712 | +0,0077 (−0,0011; +0,0169) |
| `elo_ologit` | Prioritarias · 1X2 | 281 | +0,0039 (−0,0233; +0,0240) |

**El modelo actual frente al mercado.** Con el mismo método, el peso de `poisson` es −0,10 (IC95: −0,31 a +0,10) en Resto · 1X2 y +0,04 (IC95: −0,13 a +0,19) en Resto · más/menos 2,5. Tampoco aporta información al mercado.

**Hiperparámetros elegidos.** H = 365 días, β = 0,3 y k = 3 en 36 de los 39 días; H = 365, β = 0,6 y k = 3 en los otros 3. La vida media elegida es el extremo superior de la rejilla.

**Detalles del ajuste**
- **xG aproximado.** 0,197·(tiros a puerta) + 0,062·(resto de tiros), ajustado con 21.297 partidos anteriores al 1-mar-2026. R² = 0,56 por lado.
- **Walk-forward.** 10.838 partidos objetivo desde el 7-jul (validación más evaluación), 7.439 elegibles y 52.362 ajustes de ratings. El ajuste por rival convergió en el 100 % de los casos.
- **Tiempos.** Entre la predicción del modelo actual y el saque pasan 19,5 h de mediana (p10 5,1 h; p90 72,8 h). El mercado tiene 2,93 h de antigüedad en T (p10–p90: 2,91–2,99 h), es decir, el consenso usado es de unas 5,9 h antes del saque.

## Veredicto según el protocolo

| Celda | Veredicto | Motivo |
| --- | --- | --- |
| Resto · 1X2 | **RECHAZA** | Fallan dos condiciones. El límite superior de la diferencia es +0,0127, no menor que 0. El peso es significativamente negativo (−0,38; IC95 −0,63 a −0,16): según `blend.py`, el retador es antiinformativo al lado del mercado. |
| Resto · más/menos 2,5 | **RECHAZA** | Mejora al modelo actual: el límite superior es −0,0053, menor que 0. Pero el límite inferior del peso es −0,19, no mayor que 0. |
| Prioritarias · 1X2 y más/menos 2,5 | **PENDIENTE POR MUESTRA** | 281 partidos, menos de 1.500. Las cifras de esta celda no se interpretan. |

**Veredicto global: RECHAZA.** Ninguna celda evaluable pasa la regla.

El protocolo pone más/menos 2,5 a la vez como segmento y como métrica secundaria. Con cualquiera de las dos lecturas el resultado es RECHAZA.

Conforme a `reject_rule`, el retador `e4-xg-ratings-v1` se archiva con este motivo y el modelo activo no cambia.

**Lo que este resultado no dice**
- No cierra la pregunta en las ligas prioritarias, donde el xG cubre el 96 % de la ventana pero falta muestra.
- No prueba que un proveedor de xG de pago sirva o no sirva. Lo que sí muestra es que, en las ligas con datos suficientes, los tiros y el xG de API-Football no añadieron información al mercado.

**Opciones para tu decisión, ninguna ejecutada**
- **Reevaluar las ligas prioritarias** cuando haya 1.500 partidos. Al ritmo observado (281 partidos en 31 días naturales) sería hacia finales de marzo de 2027; es una estimación que supone el mismo ritmo.
- **Abrir una línea solo de más/menos 2,5.**

Cualquiera de las dos necesita antes un protocolo v2 registrado, por la regla de parada.

## Limitaciones

1. **Ventana corta.** El modelo actual solo tiene predicciones en tiempo real desde el 25-sep (en ligas prioritarias, desde el 6-oct). Las ventanas efectivas son de 39 y 27 días. En Resto · 1X2, la prueba solo detecta con potencia del 80 % diferencias de 0,013 o más.
2. **El mercado no es el cierre.** El consenso es de unas 5,9 h antes del saque: casi nunca hay una captura entre esas 5,9 h y las 3 h previas. El test del peso se hace contra ese precio.
3. **Disponibilidad de las estadísticas en su momento.**
   - Las filas actuales tienen `fetched_at` del 29-sep-2026 o posterior en API-Football y del 24-sep en football-data, porque cada carga nueva sustituye la anterior. Por eso no se puede demostrar que PrediGol las tuviera ya el día D.
   - El protocolo solo exige que los partidos de la historia hubieran terminado antes de D, y eso se cumple.
   - En uso real, el retador dependería de que la ingesta del detalle de partido llegue a tiempo.
4. **Elección del comparador.** No hay campeón en `model_versions`. Se eligió `poisson` con una regla escrita antes de ver resultados. Frente a `dixon_coles` y `elo_ologit` la lectura es la misma: no mejora en 1X2 y sí en más/menos frente a `dixon_coles`.
5. **Equipos fuera por falta de historia.** La elegibilidad por competición excluye a los ascendidos al inicio de temporada y a los debutantes continentales: 626 de 3.364 partidos en el resto y 21 de 302 en prioritarias.
6. **Calidad del xG.** El xG es el de API-Football. En 1.452 de los 2.738 partidos del resto (53 %), menos de la mitad de la historia tenía xG y se usó el xG aproximado por tiros. El método no se validó contra los datos abiertos de StatsBomb, que la ficha permite usar solo para eso.
7. **Rejilla corta.** H = 365 quedó en el extremo de la rejilla. Probar vidas medias más largas exigiría un protocolo v2.

## Reproducción

Dónde está cada fichero en el repositorio: el script de análisis tal como se ejecutó, `backend/docs/owner/lab/IA_039/ia_lab_e4_xg.py.txt` (copia exacta, sha256 `7829e1cb…`; la extensión `.txt` lo deja fuera del linter porque es un registro del experimento, no código del producto: quítasela para ejecutarlo); el generador de la extracción, `lab/IA_039/gen_extract.py.txt`; la extracción, `lab/IA_039/extract.sql`; las consultas de la auditoría, `lab/IA_039/consultas/`; y la salida, `lab/IA_039/resultado_e4.json`.

1. **Extracción.** `python3 gen_extract.py extract.sql > extract_run.sh` genera los `\copy`, con los tramos semanales para `current` y `market`. Se ejecutan con el psql de solo lectura del brief y producen los 4 CSV con los md5 de arriba.
   - Para reproducir esta misma ventana, cambia `now()` en `extract.sql` por el instante de la extracción (11-nov-2026, entre las 05:03 y las 05:09 UTC).
2. **Análisis.**
   ```
   docker run --rm --network none --cpus=1 --memory=2g -v DIR:/lab:ro --entrypoint python predigol-backend:5ae050a9c56a /lab/ia_lab_e4_xg.py --data /lab
   ```
   - El script es puro sobre CSV: sin base de datos, sin red y determinista con la semilla 20261111. Su md5 es `cd3dd7b018d69c9c5f08fe3e47a0e36a`.
   - Con `--dry-run` solo da tamaños de muestra y la auditoría de fugas, sin métricas.
3. **Salida.** Un JSON con el sello. Aquí está en `resultado_e4.json`: es el fichero del servidor, cuyo md5 completo es 957d3905…, sin su primera línea (la del sello).
4. **Limpieza y trazabilidad.** `/tmp/lab_a09` se borró del servidor al terminar. Las consultas de la auditoría están en `consultas/q1.sh` a `consultas/q6.sh`.
