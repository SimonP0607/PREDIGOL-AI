# IA-095 · Córners y tarjetas: calibrador de conteos (AD-B07) · IA-096 · su evaluación privada (AD-E03)

Piezas AD-B07 (responsable: Modelos) y AD-E03 (IA + Modelos) del plan de la arquitectura definitiva 2026. **Todo en sombra**: ninguna cifra de esta guía llega al lector, a un pick publicado, a `decision-v1` ni a un modelo. Nada se promociona solo: un calibrador solo se usa con el veredicto del protocolo **y** la firma del dueño. `FBI_PICKS_SOURCE` sigue apagado.

## 1. Qué hace, en corto

- **IA-095 · calibrador `count-cal-v1`.** `family-v1` da la distribución de los córners y de las tarjetas de cada partido (binomial negativa por equipo; árbitro con contracción hacia 1). El calibrador corrige esa distribución **con una sola regla para todas las líneas de un conteo**: si el modelo dice «más de 4,5 tarjetas: 47 %» y en la práctica eso pasa el 43 %, el calibrador lo baja, y a la vez baja de forma coherente 3,5, 5,5, etc. Por construcción la escalera de líneas sigue ordenada (más de 8,5 siempre por encima de más de 9,5) y la distribución suma 1. Hay cuatro familias, cada una con su calibrador y su veredicto: **córners totales, córners por equipo, tarjetas totales y tarjetas por equipo**.
- **Protocolo `AD-B07`** (registrado el 17-nov-2026 antes de mirar los datos; huella `aac10f7f…299128`, fijada en `tests/unit/test_research_protocols.py`). Dice qué se mide, con qué datos, cómo se parte el tiempo y qué hace falta para **VALIDADO**, **NO VALIDADO** o **INSUFICIENTE**.
- **IA-096 · evaluación privada.** Una selección de córners o tarjetas solo entra en el ciclo de estados privado (escritor `count-eval-v1`) si cumple **las cuatro condiciones**: regla de liquidación verificable, calibrador VALIDADO **firmado por el dueño**, precio y **al menos 3 casas**. Las demás se cuentan con su motivo y no se escribe nada de ellas.

## 2. Qué se midió (LAB, 17-nov-2026, datos de producción exportados en solo lectura)

**Datos.** Partidos de las competiciones seguidas, leídos por la misma puerta que `family-v1` (`fbi.families.history`): córners con la regla `corners_ft@v1` (64.415 partidos desde el 1-nov-2023, 127 competiciones) y tarjetas con `cards_lines_ft@v1` (amarilla 1 y roja 1, de las estadísticas del equipo; 63.527 partidos). Precios: el último de cada casa antes del saque en `market.odds_quotes`, solo casas completas (las dos opciones a esa línea, margen entre 1 y 1,25), margen quitado en proporción, media de las casas, **3 casas o más** y solo medias líneas.

**Cómo.** Walk-forward en bloques de 28 días, evaluando los partidos con saque entre el **10-nov-2025 y el 10-nov-2026** (14 bloques, 360 días con partidos). En cada bloque `family-v1` se reajusta solo con partidos cuyo resultado se conocía al empezar el bloque; la dispersión y el calibrador se ajustan solo con predicciones fuera de muestra de bloques anteriores. Nada se predice, dispersa ni calibra con un partido cuyo resultado no se conocía entonces (prueba: `test_what_happens_later_never_moves_an_earlier_block`).

**Las tres condiciones de VALIDADO** (todas, con al menos 1.500 partidos en 60 días):
1. el calibrador no empeora a `family-v1` en más de 0,001 de log loss (límite superior del intervalo del 95 % por días);
2. cada línea de la escalera con 200 partidos o más queda con error de calibración (ECE) ≤ 0,03;
3. el resultado **sabe más que la media de la liga** (límite superior de la diferencia < 0).

**Resultado** (log loss medio de la escalera, menos es mejor; intervalo del 95 % por bootstrap de 360 días):

| Familia | Partidos | Calibrado − family-v1 | Calibrado − media de la liga | ECE máx. calibrado | Veredicto |
| --- | ---: | --- | --- | --- | --- |
| Córners totales (7,5 a 13,5) | 17.609 | −0,00005 [−0,00030; +0,00021] | −0,0012 [−0,0044; **+0,0021**] | 0,027 (línea 7,5) | **NO VALIDADO** |
| Córners por equipo (2,5 a 7,5) | 17.609 (35.218 equipos) | +0,00002 [−0,00007; +0,00012] | −0,0191 [−0,0243; −0,0126] | 0,012 | **VALIDADO** |
| Tarjetas totales (2,5 a 6,5) | 17.401 | **−0,0025** [−0,0033; −0,0017] | −0,0066 [−0,0094; −0,0041] | 0,025 (línea 4,5) | **VALIDADO** |
| Tarjetas por equipo (0,5 a 3,5) | 17.401 (34.802 equipos) | −0,0009 [−0,0014; −0,0004] | −0,0060 [−0,0075; −0,0046] | 0,020 | **VALIDADO** |

Cómo leerlo:

- **Córners totales: NO VALIDADO.** El calibrador no estropea nada (condiciones 1 y 2 cumplidas), pero el total de córners del modelo **no se distingue de la media de la liga**: el intervalo llega a +0,0021. Es lo mismo que ya vio F11 (`FAMILIAS_VS_MERCADO_F11.md`): el modelo sabe de cada equipo, no del total. Esta familia **no entra** en la evaluación privada.
- **Córners por equipo: VALIDADO**, con un matiz: `family-v1` ya estaba bien calibrado por equipo (ECE ≤ 0,012) y el calibrador apenas lo toca (pendiente 1,004; desplazamiento +0,035 en el último bloque). Sí supera con claridad a la media de la liga.
- **Tarjetas totales: VALIDADO, y aquí el calibrador sí arregla algo.** `family-v1` dice «más» demasiadas veces: en la línea 4,5 dice 46,8 % y pasó el 43,2 %; su ECE llega a 0,035 (no pasaría la condición 2). Calibrado dice 45,7 % y el ECE baja a 0,025. El desplazamiento del calibrador ha ido creciendo de +0,06 a −0,15 a lo largo del año: el nivel de tarjetas de las ligas baja y el modelo va por detrás.
- **Tarjetas por equipo: VALIDADO**, pero hoy **no hay mercado con 3 casas** (ver §4), así que tampoco puede entrar en la evaluación privada.

**Frente al mercado sin margen** (vara del valor, no del calibrador; solo hay precios desde el 25-sep-2026): en las cuatro familias **el mercado es algo mejor y la diferencia no es concluyente**: córners totales +0,0025 [−0,0039; +0,0088] (14.826 líneas de 2.718 partidos, 44 días, 3,8 casas de media), córners por equipo +0,0108 [−0,0030; +0,0250] (6.228 líneas), tarjetas totales +0,0091 [−0,0098; +0,0288] (1.091 líneas, 41 días, 3,5 casas). **Que un calibrador esté VALIDADO no quiere decir que haya valor**: quiere decir que sus probabilidades son honestas. El valor lo juzga AD-E02 con el precio de cada selección.

El resultado completo está en `IA_095_CORNERS_Y_TARJETAS_resultado.json` (con la huella del protocolo).

## 3. El árbitro

- **Contracción hacia 1** (la de `family-v1`, sin cambios: previa de 150 tarjetas «sin efecto», 5 partidos como mínimo). Prueba del protocolo: de los 28.977 multiplicadores aprendidos en el año, 9.511 eran de árbitros con 10 partidos conocidos o menos, y **el 100 % quedó a 0,25 o menos de 1** (el más alejado, 0,14). Ninguno de todos pasó de 0,21.
- **Solo cuenta si se conocía antes del partido**: la designación se toma como la última vista **3 horas o más antes del saque** en `core.fixture_officials`. Con esa regla solo el **8,6 %** de los partidos evaluados tenía árbitro conocido (2.494 designaciones desde el 18-ago-2025): la mayoría de los árbitros se registran después del partido.
- **Identidad** (F3 e IA-071): el árbitro se lee por su alias (`core.referee_aliases`), así que una fusión de dos fichas se aplica sola. Una grafía duplicada parte su muestra y lo acerca a 1, nunca lo exagera.
- **Lo que aporta, medido**: con y sin el multiplicador, el log loss de las tarjetas totales cambia −0,0002 [−0,0006; +0,0001]: **no se distingue de cero**. No se quita (es parte de `family-v1`), pero no se le atribuye mérito.

## 4. Precio, liquidación y convención de tarjetas (del 1-sep al 10-nov-2026)

| Mercado | Partidos con precio | Con 3 casas o más |
| --- | ---: | ---: |
| Córners total (`CORNERS_OU`) | 4.071 | 3.750 (92 %) |
| Córners local / visitante | 3.618 / 3.612 | 3.294 / 3.283 (91 %) |
| Tarjetas total (`CARDS_OU`) | 1.752 | 1.042 (59 %) |
| Tarjetas local / visitante | 1.751 / 1.751 | **0** |

- **Córners sin conteo:** de 4.061 partidos jugados con precio de córners, **650 (16,0 %) terminaron sin córners** en los datos del proveedor (IA-070 midió 18 % en otra ventana). Esas selecciones se liquidan como **`None`, nunca como pérdida** (`fbi.picks.count_settlement.settle_numbers`, probado).
- **Convención de tarjetas:** el proveedor no dice qué cuenta cada casa en «Cards Over/Under». Se liquida con `cards_lines_ft@v1` (cada tarjeta cuenta 1) y la regla viaja con cada admisión. Si una casa contara solo amarillas, **el 3,5 % de las líneas con precio (38 de 1.091) se habría liquidado distinto**: es el riesgo medido de esa ambigüedad.
- La probabilidad de «más de L» es exactamente la masa que paga la liquidación en esa línea (prueba de paridad con `count_settlement`).

## 5. La evaluación privada (IA-096)

Para cada selección de `CORNERS_OU`, `CORNERS_OU_HOME/AWAY`, `CARDS_OU`, `CARDS_OU_HOME/AWAY` que la capa de las familias (`decision-fam-v1`) decide, se comprueba **en este orden** (el primer fallo es el motivo, en las palabras del ciclo de estados):

1. regla de liquidación que lee el conteo y media línea → si no, `datos_insuficientes`;
2. calibrador **VALIDADO y firmado CHAMPION por el dueño** → si no, `sin_calibrar`;
3. al menos una casa completa en esa línea → si no, `sin_precio`;
4. al menos **3 casas** → si no, `mercado_estrecho`.

Solo las admitidas reciben su cadena de estados (la misma que deriva el ciclo, AD-D02) bajo el escritor `count-eval-v1`, en `intel.selection_lifecycle`, de solo añadido. Una vez dentro se sigue hasta su liquidación.

**Qué pasaría hoy, con estos veredictos y después de la firma:** córners por equipo y tarjetas totales podrían entrar; córners totales no (NO VALIDADO) y tarjetas por equipo no (sin 3 casas). **Hoy no entra ninguna**: ningún calibrador está firmado, `decision-fam-v1` no escribe decisiones (`FBI_FAMILY_DECISIONS` apagado: 0 en los últimos 7 días) y la tabla del ciclo (revisión 0142) aún no está en producción.

## 6. Qué NO cambia

- `family-v1` y sus filas: el código nuevo vive en `fbi/countcal`, fuera de los paquetes con huella (`MODEL_PACKAGES` y la huella de las familias). No se renueva la versión de ningún modelo.
- `decision-v1`, `decision-v2`, los picks, los parlays, la API, `web/`: nada los lee ni los importa (prueba de aislamiento).
- `intel.calibrators` e `intel.promotions` no se tocan: sus lectores (evaluación prospectiva, candidatos de promoción, vigilancia de deriva) tomarían un calibrador de conteos por uno de los suyos. Por eso hay tablas propias.

## 7. Cómo se enciende (pasos del dueño, en el servidor)

1. Tras el despliegue (migración **0152**), repetir el LAB es opcional: el veredicto de hoy ya está registrado con la huella del protocolo.
2. Guardar los calibradores actuales (uno por familia, con su veredicto): `FBI_COUNT_CALIBRATION=shadow python -m scripts.count_calibration fit --report docs/owner/IA_095_CORNERS_Y_TARJETAS_resultado.json --write` (sin `--write` solo imprime). El comando se niega si el informe no lleva la huella del protocolo AD-B07.
3. **Firmar** el que se quiera usar: `python -m scripts.count_calibration sign --id <id> --role CHAMPION --signed-by "Simon" --signature "<texto>" --confirm-owner`. La base de datos **rechaza** un CHAMPION sin VALIDADO.
4. Ver quién entraría y por qué no: `python -m scripts.count_calibration private` (solo lee). Para escribir el ciclo privado: `FBI_COUNT_EVAL=shadow … private --write` (necesita también la revisión 0142).

## 8. Cómo se apaga o se revierte

- `FBI_COUNT_EVAL` y `FBI_COUNT_CALIBRATION` nacen **off**: con ellos apagados no se escribe nada.
- Retirar un calibrador: `sign --role RETIRED`. La familia vuelve a «sin calibrar»; las filas se conservan.
- Revertir la migración 0152 borra solo sus dos tablas.

## 9. Pendiente (no hecho aquí)

- Que `decision-v2` lea la cifra calibrada de las familias y su valor con intervalo (AD-E02) y el tablero AD-K02: esta pieza deja el calibrador y la puerta de entrada; el valor y el tablero son de esas piezas.
- Programar el pase privado en el worker: hoy es un comando; no tiene sentido programarlo hasta que haya un calibrador firmado y `decision-fam-v1` en sombra.
- Córners totales: un modelo del total que sepa más que la media de la liga es un protocolo nuevo (v2), no un ajuste de este.
