# IA-097 · Valor con incertidumbre (AD-E02) · IA-098 · Correlación unificada (AD-E07)

Piezas AD-E02 y AD-E07 del plan de la arquitectura definitiva 2026 (responsable: IA, con Cuotas y Modelos). Son **dos cálculos puros
nuevos, en sombra**, en un paquete nuevo `fbi/valuation/`:

- `value-v2` (`fbi/valuation/value.py`): el **valor esperado (VE) de una selección con su intervalo**, su **cuota justa**, la **edad de su
  precio** y el **número de casas**. Con menos de 3 casas es «una sola casa» y **nunca confirma**. Sin rangos de cuota.
- `corr-v2` (`fbi/valuation/dependence.py`): **un solo cálculo de la dependencia entre dos selecciones**, que sustituye en sombra a los
  dos que hoy dan un número (parlays y portfolio) y dice siempre de dónde sale cada número.

**Lo que ve el lector no cambia. Lo publicado no cambia.** No toca `decision-v1` (`fbi/intel/decision.py`, protegido, byte a byte igual),
ni `parlay-v5`, ni los picks, ni la API, ni `web/`. `FBI_PICKS_SOURCE` sigue apagado. **Ningún modelo de lenguaje** calcula, corrige ni
elige estas cifras. Sin migración, sin interruptor, sin coste de API.

Las mediciones son de solo lectura en producción, del 17-nov-2026 (entre las 05:50 y las 06:30 UTC), con la orden nueva
`scripts/ia_value_correlation.py`.

## 1. El valor con incertidumbre (`value-v2`)

### 1.1 Qué calcula

Para una selección, una probabilidad y un precio, en el momento de la decisión (nunca el reloj):

| Campo | Qué es |
| --- | --- |
| `ev` | VE por unidad apostada: P(gana) × cuota − (1 − P(devuelve)) |
| `ev_low`, `ev_high` | Su intervalo del 95 % |
| `fair_odds` | La cuota con la que la apuesta queda en cero: (1 − P(devuelve)) / P(gana) |
| `price_age_min` | Minutos desde que se confirmó el precio |
| `books` | Cuántas casas lo cotizan; con menos de 3, `single_book` («una sola casa») |
| `verdict` | `confirmed` o el primer motivo por el que no confirma |

**Líneas con devolución y cuartos.** Una línea entera puede devolver la apuesta. Una línea de cuarto es media apuesta en cada línea vecina:
puede ganar o perder la mitad. El VE se calcula exacto con la probabilidad de ganar y de devolver (las medias de las dos mitades). Una
prueba lo comprueba contra la liquidación marcador a marcador en ocho líneas (hándicap asiático 0, −0,25, +0,75, −1; más/menos 2, 2,25,
2,75, 3).

**Dos convenciones, separadas.** La probabilidad de `picks.picks` y de `decision-v1` es *condicionada a que la apuesta se liquide*; la de
la cifra única (`forecast-v2`) no lo es. `value-v2` sabe cuál recibe y da el mismo VE que `decision-v1` con la primera (en producción:
iguales hasta el redondeo, máx. 2,8·10⁻⁶ en 18.420 filas).

### 1.2 El intervalo

Dos fuentes de incertidumbre, independientes (método delta):

1. **La probabilidad**: su propio intervalo. El de los modelos es del **90 %** (cuantiles sobre sorteos de parámetros), y se lee a ese
   nivel. Si la probabilidad está calibrada, el intervalo del número crudo se traslada al calibrado por su anchura (el error propio del
   calibrador no entra: ningún calibrador lo declara, y la lectura lo dice: `interval_basis = transported`).
2. **El precio**: pudo moverse desde que se confirmó. Su desviación crece con la edad: 0,0243 × √horas, con techo 0,066.

Esas dos cifras están **medidas en producción** (17-nov-2026): el cambio del logaritmo de la mejor cuota entre capturas consecutivas de la
misma selección (1X2, más/menos 2,5 y ambos marcan; ≥ 3 casas; los 434 partidos que empezaron entre 8 y 1 días antes):

| Separación entre capturas | Pares | Cambio típico (raíz cuadrática media) | Por √hora |
| --- | ---: | ---: | ---: |
| 2,4–3 h | 1.302 | 0,042 | 0,0243 |
| 3–6 h | 1.806 | 0,043 | 0,0202 |
| 6–12 h | 2.142 | 0,055 | 0,0189 |
| 12–24 h | 2.639 | 0,066 | 0,0152 |
| 24–48 h | 1.316 | 0,050 | 0,0101 |

La regla toma **el mayor** por √hora y **el mayor** cambio como techo: exagera la deriva de un precio viejo antes que quedarse corta. No hay
capturas separadas por menos de 2,4 h: para un precio de minutos, la regla es una extrapolación (raíz del tiempo).

### 1.3 Cuándo confirma

En este orden, el primer motivo que aplica es el veredicto:

| Veredicto | Cuándo |
| --- | --- |
| `future_price` | El precio es posterior al momento de la decisión: **fuga**, no se calcula nada (AD-A04) |
| `no_price` / `no_probability` | Falta uno de los dos |
| `no_interval` / `no_age` | La probabilidad no trae intervalo, o el precio no tiene edad |
| `single_book` | **Menos de 3 casas: nunca confirma**, por grande que sea el VE |
| `uncalibrated` | La probabilidad no está calibrada |
| `interval_includes_loss` | El intervalo del VE llega a cero o menos |
| `confirmed` | VE positivo en todo su intervalo, calibrado, con 3 casas o más |

**Sin rangos de cuota**: nada mira si la cuota es grande o pequeña. Una prueba con 3.000 casos comprueba que el veredicto depende solo del
intervalo, las casas, la calibración y la edad; otra, que el VE sube con la cuota y que el intervalo siempre contiene al punto.

### 1.4 Quién lo usa

`decision-v2` (sombra) lleva en cada decisión el bloque `value_v2`, hecho con la misma probabilidad y el mismo precio que juzgaron sus
etapas. **Ninguna etapa lo lee** (una prueba sobre 2.000 decisiones lo comprueba: si se cambia el bloque por uno absurdo, ningún estado,
motivo ni etapa cambia). La repetición (`python -m scripts.ia_decision_v2 replay --day …`) añade un resumen `value_v2`. `decision-v1` no
lo lee.

### 1.5 Medición en producción (`decision-v1`, 3 al 16-nov, días de Bogotá: 18.434 filas)

| Qué | Resultado |
| --- | --- |
| Filas con precio | 18.420 (14 sin precio) |
| Con VE, intervalo, cuota justa, edad y casas | **18.420 de 18.420 (100 %)** |
| «Una sola casa» (1 o 2 casas) | 941 (5,1 %): las 941 ya eran `RECHAZADO` por `decision-v1` (mercado fino) |
| **Confirmadas con una sola casa** | **0** |
| Precios posteriores a la decisión | 0 |
| Edad del precio | mediana 95 min (p10 14 min, p90 727 min) |
| VE puntual | mediana +1,3 % (p10 −13,8 %, p90 +5,8 %) |
| Anchura del intervalo del VE | mediana 0,82 (p10 0,41, p90 1,58) unidades por unidad apostada |
| `confirmed` | **170 (0,9 %)**: 71 CAUTELA, 87 INVESTIGACION, 12 RECHAZADO. Ninguna `APROBADO`: no hubo ninguna en la ventana |

**Lectura.** Con la incertidumbre que el propio modelo declara, casi ninguna selección tiene valor seguro: el VE puntual mediano es
positivo, pero su intervalo es muy ancho (los intervalos del 90 % de los modelos son anchos). Esto es una medida, no un umbral nuevo:
`value-v2` no decide nada hoy.

## 2. La correlación unificada (`corr-v2`)

### 2.1 Los tres cálculos de hoy

| Dónde | Qué hace |
| --- | --- |
| Parlays (`parlay-v5`) | Rechaza dos tramos del mismo partido o del mismo equipo. Entre partidos de una misma jornada usa la correlación medida (`icc-v1`) **solo si es claramente negativa** |
| Portfolio (`portfolio-corr-v1`) | Mismo partido 0,60; mismo equipo 0,30; misma competición 0,15 (ventana de 2 h) o 0,05; misma ventana 0,02 (constantes de ingeniería). Usa la correlación medida si es significativa, del signo que sea |
| `decision-v1`, filtro 8 | Una sola selección aprobable por partido. **No se toca** |

### 2.2 La regla de `corr-v2`

- **Mismo partido**: la **matriz de marcadores** del partido (IA-074), reconstruida de las filas guardadas del propio modelo: la
  correlación de las dos selecciones sale de la matriz. Si no hay matriz, o el par incluye una línea que puede devolver, queda **sin
  medir** y **no se puede combinar** en una probabilidad conjunta.
- **Mismo equipo en dos partidos**: sin medir; no se combina.
- **Misma competición y día**: la correlación medida en resultados (`icc-v1`) con su **intervalo del 95 %** y su muestra (jornadas), solo
  para lo que mide de verdad: local, empate, visitante, **más de 2,5** y ambos marcan. (`icc-v1` mide solo la línea 2,5; hoy parlays y
  portfolio la aplican también a 1,5 o 3,5; `corr-v2` no.)
- Lo demás: sin medir, o nada compartido.

Cada lectura da dos números:
- **Para una probabilidad conjunta** (parlays): el de la matriz, o el medido solo si es claramente negativo. **Una correlación positiva sin
  medir, o incierta, nunca sube la conjunta.**
- **Para un presupuesto de stake** (portfolio): el de la matriz, el medido si es significativo, o si no la constante de ingeniería; solo
  baja stakes, nunca los sube.

Propiedades probadas: simétrica, siempre entre −1 y 1, el intervalo contiene el punto; **paridad con `parlay-v5`** en los pares que mide
`icc-v1` y **con los presupuestos de `portfolio-corr-v1`** sin matriz (300 conjuntos aleatorios cada una).

### 2.3 Quién lo usa

- **Portfolio**, en sombra: `python -m scripts.ia_portfolio day --day AAAA-MM-DD --correlation-v2` añade el bloque `correlation_v2` (pares,
  grupos de presupuesto y diferencias con `portfolio-corr-v1`). **Los stakes siguen calculándose con `portfolio-corr-v1`**: una prueba
  comprueba que el informe, quitado ese bloque, es idéntico.
- **Parlays**: `parlay-v5` no lo lee. Lo leerá `parlay-v6` (AD-E06), que es su siguiente pieza.
- `decision-v1`: no lo lee (prueba de aislamiento).

### 2.4 Medición en producción: los tres cálculos frente a `corr-v2`

Selecciones que el portfolio pesaría (RECOMMENDED y CAUTION, a las 06:00 de Bogotá) del 3 al 16-nov: **12 días con 2 o más selecciones,
336 selecciones, 171 partidos, 169 con matriz**. Todos los pares: 15.679.

| Qué | Resultado |
| --- | --- |
| Correlación medida (`icc-v1`, 16-nov, 12.663 jornadas) | Las cinco **positivas y significativas, pero pequeñas** (0,009 a 0,030) |
| Pares del mismo partido | 293: parlays los rechaza; portfolio les pone 0,60; `corr-v2` mide 43 con la matriz y deja 250 sin medir (165 son hándicap con hándicap, casi todos líneas con devolución) |
| `decision-v1`, filtro 8 | **No actuó ni una vez**: 0 filas con `correlated_same_match` en 60 días (71.772 filas), porque ninguna llegó a `APROBADO` |
| Probabilidad conjunta entre partidos | `corr-v2` = `parlay-v5` en los **8.493 pares** (1 corregido: más y menos de 2,5 en la misma jornada, negativa y significativa) |
| Presupuesto del portfolio | Igual en **8.743 de 8.786** pares; solo cambia en los 43 del mismo partido con matriz (9 más altos que 0,60, 34 más bajos) |
| Correlación del mismo partido según la matriz | mediana 0,17 (p10 −0,38, p90 1,0); 15 negativas; 11 con valor absoluto ≥ 0,60 |
| Medida que `corr-v2` deja de aplicar | 4 pares de más/menos en líneas que no son 2,5 |

**Lectura.** Entre partidos los tres cálculos coinciden en la práctica, porque las correlaciones medidas son minúsculas. La diferencia real
está en el mismo partido: la constante 0,60 del portfolio es demasiado alta para pares casi independientes y demasiado baja para pares que
son el mismo suceso (por ejemplo «Local» y «Local −0,5», correlación 1), y trata como positivos pares que se excluyen (Local y Visitante).

## 3. Hallazgos que no corrige esta pieza

1. **`decision-v2` con la cifra única y líneas con devolución.** Con `--probability common --view-version forecast-v2`, la etapa 5 calcula
   el VE como (1 − devolución)(p × cuota − 1) con una `p` que ya no está condicionada. En una línea que devuelve eso **resta p × cuota ×
   devolución** al VE (en un hándicap 0 con 27 % de empate, p 0,40 y cuota 2,2: 0,24). Las etapas no se tocan aquí; `value-v2` lo calcula
   bien y la repetición cuenta la diferencia (`value_v2.ev_gap_vs_stages`). No medido en producción: hace falta ejecutar esa repetición.
2. **`icc-v1` se aplica a cualquier línea de goles.** Parlays y portfolio usan la correlación de «más de 2,5» para 1,5 o 3,5. `corr-v2` no.
3. **El intervalo de los modelos es del 90 %**, no del 95 %; `value-v2` lo lee a su nivel.

## 4. Qué no cambia

`decision-v1` (incluido su filtro 8), los estados y etapas de `decision-v2`, `parlay-v5` y sus registros, los stakes del portfolio, los
picks y su liquidación, la API y los contratos, `web/`, los modelos y calibradores, `FBI_PICKS_SOURCE`.

## 5. Cómo se activa, se repite y se revierte

- **Activación**: ninguna. Tras desplegar, la repetición de `decision-v2` lleva `value_v2` y el portfolio acepta `--correlation-v2`.
- **Repetir las mediciones** (solo lectura):
  `docker exec -w /app predigol-worker python -m scripts.ia_value_correlation drift --days 8 --json`,
  `… value --since 2026-11-03 --until 2026-11-17 --json` y `… correlation --since 2026-11-03 --until 2026-11-17 --json`.
- **Revertir**: revertir el PR. No escribe datos, no hay migración ni interruptor.

## 6. Pendiente

- **Registro de capacidades** (AD-003): dar de alta `value-v2` y `corr-v2` en `en_sombra`. El catálogo del código debe coincidir hoy con la
  semilla de la migración 0138; el alta de capacidades nuevas se hace en lote.
- **Cierre de AD-E07** («un solo cálculo en uso por parlays y portfolio»): llega cuando `parlay-v6` (AD-E06) lo lea y el portfolio pase a
  presupuestar con `corr-v2` (decisión del dueño; hoy solo lo mide).
- **Cierre de AD-E02 en las filas persistidas** de `decision-v2` (AD-D01): cuando existan, cada fila llevará el bloque `value_v2`.
- **Vara de la regla de precio** (+5,77 % frente al cierre, 2.705 selecciones, A10): no repetida aquí.
