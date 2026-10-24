# F10 — Los modelos por familia: goles por mitad, córners y tarjetas

Guía del dueño. Qué hace F10, qué se midió, qué no hace, qué queda guardado, cómo mirarlo y cómo apagarlo.

## 1. En una frase

Hasta F9 PrediGol sabía pronosticar *quién gana* y *cuántos goles hay* (los cinco mercados que funcionan). F10 le enseña a pronosticar
*cuántos* de otras cosas —goles de cada parte, córners, tarjetas amarillas y tarjetas en total— con **un modelo por familia**, entrenado con
el historial de partidos terminados. Los pronósticos se guardan como **investigación en SOMBRA**: ningún usuario los ve, no tienen precio,
no proponen apuestas y **los cinco mercados que ya funcionan no cambian en nada**. Que se enseñen, que se fijen precios con ellos o que
se conviertan en apuestas es una decisión posterior (F11 y la puerta de F14), y para ello falta el historial de precios que F1 sigue juntando.

## 2. Qué se construyó

* **Los modelos** (`fbi.families`). En cada competición, cada equipo tiene una fuerza de ataque y una de defensa (encogidas hacia la
  media) y el número de córners o tarjetas de cada lado se modela con una binomial negativa (los goles de cada parte, con una Poisson).
  La dispersión de la binomial se mide **fuera de muestra** y mezclando competiciones: cada competición se ajusta 120 días atrás y
  predice lo jugado desde entonces, y hacen falta al menos 300 partidos así. El resultado de un partido solo cuenta como entrenamiento
  **6 horas después de su inicio**. Una competición se ajusta con al menos 120 partidos, un equipo se pronostica con al menos 8, y una
  competición con más de 250 equipos (los amistosos de clubes) nunca se ajusta.
* **La evaluación** (`python -m scripts.families evaluate`). Para cada competición, por bloques de 28 días: ajusta con lo ya conocido,
  predice el bloque, avanza. Se compara con **«no saber nada de los equipos»** (el promedio de la competición con el mismo
  decaimiento en el tiempo). La ganancia se da en *nats por partido* (puntuación logarítmica: cuánto más probabilidad se puso a lo que
  pasó que el promedio de la competición; positiva es mejor, y el «± error» es un error estándar). Los hiperparámetros (decaimiento y
  encogimiento) se eligen en los 180 días ANTERIORES a la ventana de prueba, nunca en ella.
* **La comprobación de calibración** (`--calibration`). Con las predicciones en el orden en que se jugaron, la primera mitad ajusta
  una recalibración (un desplazamiento, y un desplazamiento con inclinación) y la segunda la califica. Nunca se califica con los
  partidos que la ajustaron.
* **El almacén** (`models.match_forecasts`, el de F5, versión **`family-v1`**). La página del pronóstico de un partido lee solo la
  versión `forecast-v1`, así que nadie ve estas filas. Cada mercado queda siempre **UNCALIBRATED** (base `no_champion`, sin intervalo): ninguna
  familia tiene calibrador ni lo tendrá hasta que la puerta del plan (al menos 300 apuestas y un CLV no negativo, que necesita el
  historial de precios de F1) lo diga. Una fila nueva se escribe cuando el mercado es nuevo, cuando cambió el modelo o su versión, o cuando
  alguna probabilidad se movió medio punto.
* **Cuatro modelos**, registrados con la familia de registro **`counts`** (migración 0093, que solo añade ese valor a una restricción
  de la tabla del registro; no escribe ninguna fila y se deshace): `family-goals_halves` (familia `GOALS_HALF`), `family-corners_ft`
  (`CORNERS`), `family-cards_lines_ft` (`CARDS`) y `family-yellow_ft` (`YELLOW`). Su **versión** es `1.0.0/<especificación>@fc<huella>`: la
  huella resume el código de `fbi.families` y el del ajuste de fuerzas que reutilizan (`models/goals.py`); un cambio ahí es una versión
  nueva, un cambio en cualquier otro sitio no. El código de los modelos de goles NO se tocó (su huella sigue siendo `mc9a7bec97ca`).
* **El árbitro en las tarjetas.** `family-cards_lines_ft` y `family-yellow_ft` multiplican las medias de los dos lados por el multiplicador del árbitro del partido
  cuando ese árbitro ya está asignado (la identidad que fijó F3, vista antes del momento del cálculo; uno que aparece después no cuenta) y tiene
  al menos 5 partidos conocidos. El multiplicador de un árbitro son las tarjetas de sus partidos entre las que los equipos explicaban,
  encogidas hacia «sin efecto» con un prior de 150 tarjetas (unos 30 partidos). Si el árbitro no está asignado, o es nuevo, el partido
  se pronostica sin él, y cuando el árbitro aparece el pronóstico se reescribe. La huella de lo que se usó guarda al árbitro y a su multiplicador;
  la dispersión de la familia se mide con los mismos multiplicadores.
* **El paso del worker `family_forecasts`**, cada 3 horas (`FBI_FAMILY_FORECAST_MINUTES`, 180): pronostica los partidos de las competiciones
  seguidas que empiezan dentro de los próximos 4 días (y no dentro de los próximos 15 minutos). Solo lee la base: **0 peticiones al proveedor, 0 IA**. Cada familia se
  escribe entera o nada, y si una falla las otras siguen. Deja una corrida en el registro solo cuando escribió o falló. La dispersión se mide en
  la primera pasada de cada día y las demás la reutilizan (la guarda el proceso del worker: un reinicio la mide otra vez). Se apaga con
  `FBI_FAMILY_FORECASTS=0`.

## 3. Cuánto aciertan

Todas las cifras son de la ventana de prueba **2025-10-16 a 2026-10-23** (partidos que el modelo no había visto, entrenado solo con lo conocido
antes de cada bloque). «Aporta» significa que la ganancia supera dos veces su error; «no se distingue de no saber nada» significa que no
supera ese listón. Ninguna de estas cifras compara con el mercado: eso necesita precios de cierre y es la puerta de F14.

### 3.1 Goles de cada parte (`family-goals_halves`; decaimiento 0,0019, encogimiento 8)

22.777 predicciones. Las dos partes se pronostican por separado y de ellas se derivan el descanso/final, la mitad con más goles, ambos
marcan por mitad y los totales. La correlación residual entre las dos partes es **0,032 ± 0,007**: pequeña pero no nula.

| Qué se pronostica | Ganancia por partido (± error) | Lectura |
|---|---|---|
| Resultado de la primera parte (1-X-2) | +0,0229 ± 0,0011 | aporta |
| Resultado de la segunda parte (1-X-2) | +0,0276 ± 0,0013 | aporta |
| Descanso/final (las 9 combinaciones) | +0,0476 ± 0,0016 | aporta |
| Mitad con más goles | -0,0022 ± 0,0006 | empeora |
| Ambos marcan en la primera parte | +0,0003 ± 0,0005 | no se distingue de no saber nada |
| Ambos marcan en la segunda parte | -0,0003 ± 0,0006 | no se distingue de no saber nada |
| Primera parte, más de 0,5 goles | +0,0010 ± 0,0006 | no se distingue de no saber nada |
| Primera parte, más de 1,5 goles | +0,0013 ± 0,0007 | no se distingue de no saber nada |
| Segunda parte, más de 1,5 goles | +0,0009 ± 0,0007 | no se distingue de no saber nada |
| Segunda parte, más de 2,5 goles | +0,0015 ± 0,0007 | aporta |

### 3.2 Córners (`family-corners_ft`; decaimiento 0,0019, encogimiento 32)

18.260 predicciones. **Los equipos se reparten los córners más que sumarlos**: lo que cada lado hace se puede pronosticar, y quién tiene más
también, pero el total del partido apenas.

| Qué se pronostica | Ganancia por partido (± error) | Lectura |
|---|---|---|
| Cuántos córners hace el equipo local | +0,0378 ± 0,0020 | aporta |
| Cuántos córners hace el visitante | +0,0391 ± 0,0018 | aporta |
| El total de córners del partido | +0,0017 ± 0,0013 | no se distingue de no saber nada |
| Quién tiene más córners | +0,0423 ± 0,0019 | aporta |

Calibración de las líneas (probabilidad media de «más de» contra lo que pasó):

| Línea | Se dijo (media) | Pasó | Error de calibración | Ganancia por apuesta |
|---|---|---|---|---|
| total más de 8,5 | 60,4 % | 60,9 % | 1,4 puntos | +0,0012 ± 0,0010 |
| total más de 9,5 | 48,7 % | 49,4 % | 1,6 puntos | +0,0012 ± 0,0010 |
| total más de 10,5 | 37,6 % | 38,1 % | 1,7 puntos | +0,0013 ± 0,0010 |
| total más de 11,5 | 27,8 % | 28,0 % | 1,7 puntos | +0,0016 ± 0,0010 |
| local más de 3,5 | 69,8 % | 70,3 % | 0,9 puntos | +0,0206 ± 0,0013 |
| local más de 4,5 | 55,3 % | 56,2 % | 1,1 puntos | +0,0226 ± 0,0015 |
| local más de 5,5 | 41,5 % | 42,7 % | 1,4 puntos | +0,0230 ± 0,0015 |
| local más de 6,5 | 29,6 % | 30,3 % | 0,8 puntos | +0,0231 ± 0,0015 |
| visitante más de 3,5 | 58,2 % | 57,9 % | 0,9 puntos | +0,0236 ± 0,0013 |
| visitante más de 4,5 | 42,5 % | 42,4 % | 0,8 puntos | +0,0238 ± 0,0014 |
| visitante más de 5,5 | 29,3 % | 29,4 % | 0,9 puntos | +0,0246 ± 0,0014 |
| visitante más de 6,5 | 19,2 % | 19,5 % | 0,6 puntos | +0,0211 ± 0,0013 |

Se recalibró con la primera mitad (hasta el 2026-03-27) de las 18.260 predicciones y se midió en la segunda. En esa segunda mitad, el error de calibración más alto antes de recalibrar fue 1,9 puntos (total 9,5); la recalibración con inclinación lo dejó en 1,0 puntos y su mejor ganancia fue +0,0006 ± 0,0005 nats por apuesta (total 8,5).

### 3.3 Tarjetas contadas como líneas (`family-cards_lines_ft`; decaimiento 0,0019, encogimiento 32)

18.024 predicciones (cada tarjeta cuenta una: las amarillas más las rojas). Las tablas de esta sección son las del modelo de equipos **sin árbitro**,
que es lo que se pronostica cuando el árbitro no está asignado.

| Qué se pronostica | Ganancia por partido (± error) | Lectura |
|---|---|---|
| Cuántas tarjetas hace el equipo local | +0,0095 ± 0,0010 | aporta |
| Cuántas tarjetas hace el visitante | +0,0088 ± 0,0010 | aporta |
| El total de tarjetas del partido | +0,0069 ± 0,0010 | aporta |
| Quién tiene más tarjetas | +0,0093 ± 0,0009 | aporta |

**Con el árbitro.** Con el multiplicador del árbitro (prior de 150 tarjetas), la ganancia por partido sobre el mismo modelo sin árbitro es local +0,0031 ± 0,0006, visitante +0,0032 ± 0,0006, total +0,0061 ± 0,0009 (medida en el 81 % de los partidos que tenían un árbitro con multiplicador; el total sube a +0,0076 contando solo esos). La dispersión del total baja de 0,0094 a 0,0067.

Cómo se eligió el prior (la ganancia es la del árbitro sobre el mismo modelo sin él; mayor prior, menos peso al árbitro):

| Prior del árbitro | Ganancia del total | Ganancia local | Ganancia visitante |
|---|---|---|---|
| 50 tarjetas | +0,0047 ± 0,0013 | +0,0026 ± 0,0008 | +0,0023 ± 0,0009 |
| 150 tarjetas | +0,0061 ± 0,0009 | +0,0031 ± 0,0006 | +0,0032 ± 0,0006 |
| 400 tarjetas | +0,0049 ± 0,0005 | +0,0025 ± 0,0003 | +0,0027 ± 0,0004 |

Calibración de las líneas, del modelo sin árbitro (probabilidad media de «más de» contra lo que pasó):

| Línea | Se dijo (media) | Pasó | Error de calibración | Ganancia por apuesta |
|---|---|---|---|---|
| total más de 3,5 | 64,6 % | 61,7 % | 3,0 puntos | +0,0049 ± 0,0008 |
| total más de 4,5 | 47,0 % | 43,5 % | 3,5 puntos | +0,0045 ± 0,0008 |
| total más de 5,5 | 31,3 % | 28,2 % | 3,1 puntos | +0,0041 ± 0,0008 |
| local más de 1,5 | 62,0 % | 60,8 % | 1,3 puntos | +0,0068 ± 0,0007 |
| local más de 2,5 | 36,1 % | 33,0 % | 3,0 puntos | +0,0067 ± 0,0008 |
| visitante más de 1,5 | 68,2 % | 67,5 % | 0,8 puntos | +0,0056 ± 0,0008 |
| visitante más de 2,5 | 43,0 % | 40,6 % | 2,4 puntos | +0,0067 ± 0,0008 |

Se recalibró con la primera mitad (hasta el 2026-03-24) de las 18.024 predicciones y se midió en la segunda. En esa segunda mitad, el error de calibración más alto antes de recalibrar fue 5,1 puntos (total 4,5); la recalibración con inclinación lo dejó en 3,3 puntos y su mejor ganancia fue +0,0036 ± 0,0005 nats por apuesta (total 4,5).

### 3.4 Tarjetas amarillas (`family-yellow_ft`; decaimiento 0,0019, encogimiento 32)

18.024 predicciones (tablas del modelo de equipos sin árbitro).

| Qué se pronostica | Ganancia por partido (± error) | Lectura |
|---|---|---|
| Cuántas amarillas hace el equipo local | +0,0083 ± 0,0009 | aporta |
| Cuántas amarillas hace el visitante | +0,0083 ± 0,0009 | aporta |
| El total de amarillas del partido | +0,0068 ± 0,0009 | aporta |
| Quién tiene más amarillas | +0,0089 ± 0,0008 | aporta |

**Con el árbitro.** Con el multiplicador del árbitro (prior de 150 amarillas), la ganancia por partido sobre el mismo modelo sin árbitro es local +0,0027 ± 0,0005, visitante +0,0030 ± 0,0005, total +0,0057 ± 0,0008 (medida en el 81 % de los partidos que tenían un árbitro con multiplicador; el total sube a +0,0071 contando solo esos). Las amarillas son de tipo Poisson (sin dispersión extra) con y sin árbitro.

Cómo se eligió el prior (misma lectura que en las tarjetas):

| Prior del árbitro | Ganancia del total | Ganancia local | Ganancia visitante |
|---|---|---|---|
| 50 amarillas | +0,0045 ± 0,0012 | +0,0023 ± 0,0008 | +0,0022 ± 0,0008 |
| 150 amarillas | +0,0057 ± 0,0008 | +0,0027 ± 0,0005 | +0,0030 ± 0,0005 |
| 400 amarillas | +0,0046 ± 0,0005 | +0,0022 ± 0,0003 | +0,0024 ± 0,0003 |

Calibración de las líneas, del modelo sin árbitro (probabilidad media de «más de» contra lo que pasó):

| Línea | Se dijo (media) | Pasó | Error de calibración | Ganancia por apuesta |
|---|---|---|---|---|
| total más de 2,5 | 79,0 % | 77,3 % | 1,7 puntos | +0,0034 ± 0,0006 |
| total más de 3,5 | 61,7 % | 59,1 % | 2,5 puntos | +0,0052 ± 0,0007 |
| total más de 4,5 | 43,4 % | 40,1 % | 3,2 puntos | +0,0048 ± 0,0008 |
| local más de 1,5 | 59,6 % | 59,0 % | 0,7 puntos | +0,0063 ± 0,0007 |
| local más de 2,5 | 33,5 % | 30,8 % | 2,7 puntos | +0,0062 ± 0,0007 |
| visitante más de 1,5 | 65,7 % | 65,9 % | 0,7 puntos | +0,0053 ± 0,0007 |
| visitante más de 2,5 | 40,0 % | 38,1 % | 1,9 puntos | +0,0066 ± 0,0008 |

Se recalibró con la primera mitad (hasta el 2026-03-24) de las 18.024 predicciones y se midió en la segunda. En esa segunda mitad, el error de calibración más alto antes de recalibrar fue 4,8 puntos (total 4,5); la recalibración con inclinación lo dejó en 3,3 puntos y su mejor ganancia fue +0,0028 ± 0,0003 nats por apuesta (total 4,5).

## 4. Lo que se encontró en los datos

* **Las tarjetas «solo de eventos» están incompletas.** Entre 2022-10-17 y 2026-10-23, donde un partido no tiene estadísticas por equipo y sus
  tarjetas salen solo de los eventos (11.201 partidos), la media es de 1,75 amarillas por partido y el 54 % de ellos tiene cero,
  frente a 4,29 en los 81.758 partidos que sí tienen estadísticas por equipo. Un modelo entrenado con las dos cosas mezclaría dos niveles.
* **El filtro «eventos = estadísticas» también era un sesgo (corregido durante F10).** El proveedor deja la roja **vacía** cuando no la hubo
  (con las dos rojas vacías, los eventos muestran una roja en el 0,0 % de 15.427 partidos). Pedir que la roja estuviera informada elegía los
  partidos que tuvieron roja (58 % de ellos): un historial de 5,5–6,3 tarjetas por partido hasta agosto de 2026 y de 4,0–4,3 desde que el proveedor
  escribe los ceros, y un modelo que en los últimos meses decía «más de 4,5» al 65 % cuando pasaba al 54 %. Pedir que los eventos coincidieran con las
  estadísticas era otra selección. La regla vigente: las amarillas y las tarjetas contadas como líneas se leen de las estadísticas por equipo
  (una roja vacía vale cero; sin prórroga); las demás medidas de tarjetas, de eventos cuyas amarillas coinciden, equipo a equipo, con las
  estadísticas. Resultado: 81.435 partidos entre 2022-10-18 y 2026-10-18, con una media de 4,29 amarillas y
  4,50 tarjetas (como líneas) por partido; el 98,7 % tiene árbitro identificado.
* **Para F11:** el campo `cards_consistent` de la vista `market.fixture_outcomes` (F9) tiene ese mismo sesgo. F11 debe liquidar las tarjetas
  con la regla de arriba y no con ese campo; y tratar como **no verificadas** las tarjetas que salen solo de eventos.
* **El árbitro sí importa, con los datos corregidos.** Con el historial sesgado de antes no se veía ningún efecto; con las tarjetas leídas de las
  estadísticas por equipo, el multiplicador del árbitro aporta lo que muestran las secciones 3.3 y 3.4. La advertencia es la cobertura en vivo:
  medido en solo lectura el 23-oct-2026, 220 de los 649 partidos de los próximos 4 días tenían árbitro asignado en PrediGol (≈ 40 % dentro de las
  48 horas previas, ≈ 3 % a más de 72), así que la mejora medida solo llega a esos partidos y el resto se pronostica sin árbitro.
* **Las tarjetas bajaron en los últimos meses.**
  Entre el primer trimestre de 2023 y el segundo de 2026 la media de amarillas por partido se movió entre 4,17 y 4,56; en el 3.º trimestre de 2026
  fue 3,94 (4.777 partidos); en el 4.º trimestre de 2026 fue 3,90 (1.589 partidos, hasta el 2026-10-18). En la ventana de prueba, las amarillas
  por partido fueron 4,27 en la primera mitad y 4,03 en la segunda.
  La mayor parte es mezcla de competiciones: desde septiembre entran más ligas femeninas y copas menores con muchas menos tarjetas (medido en
  solo lectura el 23-oct-2026, las amarillas por partido son 1,7 en la Damallsvenskan sueca, 2,3 en la FA WSL y 2,2 en la Champions League
  femenina, y los partidos con cero amarillas pasaron de 0,1–0,6 % a 1,6–2,4 % sin que los eventos del proveedor lo contradigan), más una
  bajada pequeña dentro de cada liga (mediana −0,13 amarillas por partido entre las 15 competiciones con al menos 100 partidos en cada
  periodo, 11 de ellas a la baja). Cada competición se ajusta por separado, así que la mezcla no afecta al modelo, pero la bajada dentro de
  cada liga hace que un modelo entrenado con el pasado diga «más de» algo alto en la segunda mitad de la ventana (se ve en los errores de
  calibración de las tablas); una recalibración fijada en la primera mitad lo corrige solo en parte, porque un calibrador fijo no sigue una
  deriva. Además, las estadísticas de los últimos días cuentan algo menos de amarillas que los eventos: en octubre de 2026, en los 1.594
  partidos que tienen las dos fuentes, 3,89 amarillas por partido en las estadísticas contra 4,02 en los eventos, y desde septiembre hay
  354 partidos donde los eventos cuentan más (1,16 amarillas más de media) cuyas estadísticas se habían leído una mediana de 26 horas
  después del inicio (medido en solo lectura el 23-oct-2026). Por eso F11 debe esperar a una lectura posterior de las estadísticas, o a que las
  dos fuentes coincidan, antes de liquidar tarjetas. Queda como mejora para F12 corregir el nivel con lo más reciente, medido en la misma
  pasada fuera de muestra.
* **Los partidos con prórroga** no entran en córners ni tarjetas (el proveedor no dice si su total incluye la media hora extra), y un
  desempate a penaltis nunca cuenta como goles.
* **Neutral.** Los modelos de F10 ignoran la marca de campo neutral (la regla de neutral de F0 sigue sin promover; F10 no decide eso por
  los modelos de goles).

## 5. Lo que F10 NO hace

* No pone **precio**, ni **valor**, ni **apuesta**: la capa de decisión no lee estas filas.
* No los **muestra**: la página del pronóstico lee `forecast-v1`. Enseñarlos (`FBI_FORECAST_USERS`, o un bloque nuevo) es decisión suya.
* No tiene **calibrador**: las probabilidades guardadas son las del modelo, marcadas UNCALIBRATED. La comprobación de la sección 3 dice
  si una recalibración las arreglaría, pero no se aplica a nada.
* No se **compara con el mercado**: falta el historial de precios (F1).
* No usa **contexto** (derbis, eliminatorias, alineaciones, IA): son modelos de fuerza de equipo.
* El total de córners **no tiene habilidad demostrada**: se guarda, pero no debe leerse como un pronóstico útil.

## 6. Cómo mirar lo guardado (solo lectura)

```sql
-- cuántas filas hay, por modelo (todas deben ser family-v1 y UNCALIBRATED)
SELECT m.name, f.version, f.calibration, count(*) AS filas, count(DISTINCT f.fixture_id) AS partidos, max(f.known_at) AS ultima
  FROM models.match_forecasts f
  JOIN models.model_versions v ON v.id = f.model_version_id
  JOIN models.model_registry m ON m.id = v.model_id
 WHERE m.family = 'counts'
 GROUP BY 1, 2, 3 ORDER BY 1;
```

Cada mercado de un partido suma 1 (las probabilidades más el empuje) y todas las claves existen en `market.markets`.
La corrida de cada paso, cuando escribe, queda en `raw.ingestion_runs` con `job_type = 'family_forecasts'` y sus notas dicen qué escribió cada
familia. Cada primera pasada escribe del orden de 130 filas por partido y unos 20 MB en total; después solo cambia lo que se movió.

## 7. Interruptores

| Interruptor | Qué hace | Valor por defecto |
|---|---|---|
| `FBI_FAMILY_FORECASTS` | enciende o apaga el paso `family_forecasts` (`0`, `off`, `false` o `no` lo apagan) | encendido |
| `FBI_FAMILY_FORECAST_MINUTES` | cada cuántos minutos corre | 180 |

Apagarlo no borra lo ya escrito; las filas son de solo añadir. Deshacer la migración 0093 (`alembic downgrade 0092`) sí borra los modelos
de la familia `counts`, sus versiones y sus pronósticos.

## 8. Decisiones que quedan abiertas

1. **¿Se enseñan a los usuarios?** Hoy no. Antes habría que decidir el aviso («investigación, sin calibrar») y la calibración.
2. **El historial de precios de F1** decide cuándo se puede comparar con el mercado y, solo entonces, calibrar y valorar.
3. **F11** (liquidación, decisión e IA por familia) debe adoptar la regla de tarjetas de la sección 4.
4. **Contexto** (derbis, eliminatorias, IA): no se ha hecho; cambiaría la versión de los modelos.

## 9. Resultado en producción

**La entrega.** F10 se desplegó el 24 de octubre de 2026 (de 03:22 a 03:36 UTC; el despliegue entero duró 13 min 25 s). Antes de empezar se hizo una
copia de seguridad y se probó que se restaura (472 s y 811 s), y el propio despliegue hizo otra (476 s). La migración 0093 se aplicó sin esperar
ningún bloqueo (se vigiló cada 3 segundos durante todo el despliegue) y el código de los modelos de goles no cambió: su huella sigue siendo
`mc9a7bec97ca`. Los pronósticos de goles de siempre (`forecast-v1`) siguieron escribiéndose sin interrupción.

**La primera pasada** del worker corrió el mismo día de 04:13:00 a 04:23:40 UTC (**10 min 40 s**: la primera de cada día mide la dispersión de
cada familia, las demás la reutilizan, y un reinicio del worker la vuelve a medir). Pronosticó 635 partidos de los próximos 4 días, 32 de ellos
sin ajuste posible, y escribió **62.496 filas `family-v1` sin ningún fallo**:

| Modelo | Partidos | Mercados escritos | Filas | Competiciones ajustadas | Sin ajustar (historial corto / equipo desconocido) |
|---|---|---|---|---|---|
| `family-goals_halves` | 516 | 12.900 | 33.024 | 81 | 1 / 86 |
| `family-corners_ft` | 445 | 6.675 | 14.240 | 73 | 9 / 84 |
| `family-cards_lines_ft` | 448 (175 con árbitro) | 3.136 | 6.272 | 73 | 9 / 81 |
| `family-yellow_ft` | 448 (175 con árbitro) | 4.032 | 8.960 | 73 | 9 / 81 |

Lo que se comprobó al terminar, todo como estaba previsto: todas las filas son `family-v1`, `UNCALIBRATED` y `no_champion`; ningún mercado se aparta de
1 en más de 0,0001; las versiones de tarjetas y amarillas dicen `referee=150.0` y llevan «referee» entre sus variables; cada partido tiene un solo
pronóstico por modelo (aún no hubo que reescribir ninguno por la llegada de un árbitro); las claves de mercado existen todas; y la tabla
`models.match_forecasts` pasó a ocupar 33 MB en total (74.000 filas, de ellas 62.496 de las familias: unas 98 por partido, entre 14 y 64 por modelo).
Mientras corría el cálculo (seis hilos de numpy, la carga de la máquina subió a 6 sobre sus 6 núcleos) las capturas en vivo siguieron a su ritmo
(24 de cuotas y 12 de partidos en 12 minutos, las que corresponden a su cadencia).

**Qué falta.** Medir si aciertan de verdad. La herramienta (F11, que llega con la próxima entrega) es `python -m scripts.families score --days 14`
(solo lectura): compara cada pronóstico guardado antes del inicio con lo que pasó y, aparte, con el precio de las casas. Los primeros partidos
pronosticados se juegan hoy mismo, así que hay con qué medir en unos días. Nada de esto cambia lo que ve un usuario.
