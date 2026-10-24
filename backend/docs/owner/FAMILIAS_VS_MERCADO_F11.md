# Las familias contra el mercado (F11.3) · guía del propietario

*Medido el 24 de octubre de 2026 sobre los precios que el reloj de precios (F1) guarda desde el 25 de septiembre. Todo sigue en SOMBRA: ninguna cifra de esta guía llega a un modelo, a un precio, a una decisión ni a un pick.*

## 1. Qué pregunta responde

El marcador de F11.2 dice si las probabilidades que da una familia fueron correctas: «cuando dijo 60 %, ¿ocurrió el 60 % de las veces?». Es necesario, pero no basta para ganar dinero: un modelo puede estar bien calibrado y saber menos que las casas de apuestas, y entonces ningún precio se le gana. La pregunta que decide si una familia puede dar valor es otra: **¿sabía el modelo algo que el mercado no sabía?** Para responderla se pone, sobre los mismos partidos y los mismos resultados, la pérdida logarítmica (*log loss*, en nats por partido; menos es mejor) del modelo junto a la del propio mercado, que es la probabilidad de las cuotas con su margen quitado.

## 2. Cómo se construye la probabilidad del mercado

- Por cada casa se toma su último precio de cada opción de ese mercado y esa línea. Solo vale una casa **completa** (todas las opciones cotizadas a esa línea) con un margen creíble: por encima de 1 (sin margen es un precio caduco o roto) y como mucho 1,25 (con más no es un precio).
- Cada casa se limpia de su margen por su cuenta, repartiéndolo en proporción: la probabilidad implícita de cada opción dividida por la suma de todas. Después se promedian las casas.
- **Con menos de 3 casas no hay consenso y no se compara.**
- Se mira en dos momentos: el **último precio** antes del inicio (el cierre) y **24 horas antes** del inicio, cuando se tomaría un pick. La medición de hoy añade 6 horas antes.
- Solo mercados de dos o tres opciones exclusivas (más/menos, ambos marcan, par/impar, empate no apuesta y 1X2) y solo líneas donde no puede haber devolución (sin línea, o con «medio»: 9,5, no 10 ni 10,25): en una línea con devolución la probabilidad justa de las casas es la de la apuesta que se liquida, y la del modelo no.

## 3. Cómo se lee

*Mercado − modelo* es la diferencia de *log loss*, con su error estándar agrupado por partido (las líneas de un mismo partido no son observaciones independientes). **Positivo: el modelo fue mejor que el mercado. Negativo: ganó el mercado.** Una diferencia dentro de su error estándar no se distingue de cero.

\*La *señal extra* es el coeficiente que recibe «modelo − mercado» (en logit) en una regresión de lo ocurrido: 0 significa que el modelo no añade nada a lo que ya dice el mercado, 1 que habría que fiarse del modelo por completo, y un valor entre medias que conviene mezclarlos. Con un error grande no se puede afirmar nada.

## 4. Resultado: córners

Una línea por partido (la más cercana al 50 % en el mercado), con el modelo de F10 reconstruido hacia delante en bloques de 7 días: nunca vio el partido que pronostica.

| Mercado | Momento | Partidos | Dijo el modelo | Dijo el mercado | Ocurrió | Log loss modelo | Log loss mercado | Mercado − modelo | Señal extra* |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| total del partido | último precio | 1.268 | 47,3 % | 49,9 % | 52,7 % | 0,6932 | 0,6892 | −0,0040 ± 0,0032 | +0,53 ± 0,28 |
| total del partido | 6 h antes | 1.187 | 47,2 % | 49,8 % | 53,1 % | 0,6953 | 0,6895 | −0,0058 ± 0,0033 | +0,38 ± 0,29 |
| total del partido | 24 h antes | 785 | 47,7 % | 49,8 % | 55,0 % | 0,6980 | 0,6904 | −0,0075 ± 0,0041 | +0,30 ± 0,34 |
| equipo local | último precio | 1.179 | 47,7 % | 49,9 % | 49,5 % | 0,7045 | 0,6873 | −0,0172 ± 0,0046 | −0,24 ± 0,20 |
| equipo local | 6 h antes | 1.102 | 47,7 % | 50,0 % | 51,0 % | 0,7055 | 0,6899 | −0,0156 ± 0,0046 | −0,17 ± 0,21 |
| equipo local | 24 h antes | 405 | 47,7 % | 50,0 % | 50,4 % | 0,6970 | 0,6886 | −0,0084 ± 0,0073 | +0,11 ± 0,37 |
| equipo visitante | último precio | 1.181 | 46,8 % | 49,8 % | 52,4 % | 0,7011 | 0,6904 | −0,0106 ± 0,0048 | +0,26 ± 0,19 |
| equipo visitante | 6 h antes | 1.105 | 47,0 % | 50,0 % | 51,9 % | 0,6972 | 0,6889 | −0,0083 ± 0,0046 | +0,30 ± 0,21 |
| equipo visitante | 24 h antes | 406 | 47,4 % | 49,9 % | 54,4 % | 0,6992 | 0,6826 | −0,0166 ± 0,0071 | −0,07 ± 0,37 |

**Quién tiene más córners** (1X2 del conteo; tres opciones):

| Momento | Partidos | Log loss modelo | Log loss mercado | Mercado − modelo |
|---|---:|---:|---:|---:|
| último precio | 1.042 | 0,8790 | 0,8623 | −0,0167 ± 0,0053 |
| 6 h antes | 974 | 0,8742 | 0,8621 | −0,0121 ± 0,0052 |
| 24 h antes | 422 | 0,8703 | 0,8658 | −0,0045 ± 0,0082 |

Lectura: en el **total** el mercado gana por poco y sin certeza (−0,004 ± 0,003 al cierre), y el modelo se queda corto de nivel (dijo 47 % de «más» cuando ocurrió el 53 %). **Por equipo y en «quién tiene más» el mercado gana con claridad** al cierre (entre 2,2 y 3,7 errores estándar). A 24 horas la imagen es la misma, con el mercado por delante en todos los casos, pero con menos partidos y más error. En el total hay un indicio de señal propia (+0,5 ± 0,3 al cierre): no es una prueba.

## 5. Resultado: tarjetas

| Mercado | Momento | Partidos | Dijo el modelo | Dijo el mercado | Ocurrió | Log loss modelo | Log loss mercado | Mercado − modelo | Señal extra* |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| total del partido | último precio | 410 | 50,9 % | 49,4 % | 44,6 % | 0,6910 | 0,6821 | −0,0089 ± 0,0079 | +0,21 ± 0,32 |
| total del partido | 6 h antes | 345 | 50,5 % | 49,7 % | 45,8 % | 0,6853 | 0,6850 | −0,0003 ± 0,0082 | +0,52 ± 0,37 |
| total del partido | 24 h antes | 125 | 51,2 % | 50,2 % | 48,0 % | 0,6814 | 0,6839 | +0,0025 ± 0,0137 | +0,58 ± 0,64 |

El modelo lleva el efecto del árbitro (un prior de 150 tarjetas), como en producción. Solo hay 410 partidos y la diferencia no es concluyente. Las **amarillas** no se pueden comparar: el reloj de precios guarda una sola casa para ellas, y con menos de 3 no hay consenso.

## 6. Si se hubiera apostado con el modelo tal cual (sin calibrar)

Apuestas simuladas de 1 unidad al **mejor precio de las casas** cuando el modelo veía un valor esperado (EV) de al menos 3 %, una por partido. «EV al probabilidad del mercado» es lo que valía ese mismo precio según el consenso de las casas.

Córners:

| Mercado | Momento | Apuestas | EV que creía el modelo | EV al probabilidad del mercado | Rendimiento real |
|---|---|---:|---:|---:|---:|
| total del partido | último precio | 711 | +10,0 % | −2,9 % | −0,5 % ± 3,7 % |
| total del partido | 24 h antes | 365 | +9,8 % | −3,6 % | −5,0 % ± 5,1 % |
| equipo local | último precio | 684 | +13,0 % | −3,7 % | −6,2 % ± 3,7 % |
| equipo local | 24 h antes | 210 | +12,2 % | −3,6 % | −0,9 % ± 6,8 % |
| equipo visitante | último precio | 729 | +13,1 % | −3,5 % | −2,0 % ± 3,6 % |
| equipo visitante | 24 h antes | 232 | +11,6 % | −3,7 % | −16,7 % ± 6,3 % |

Tarjetas (total):

| Mercado | Momento | Apuestas | EV que creía el modelo | EV al probabilidad del mercado | Rendimiento real |
|---|---|---:|---:|---:|---:|
| total del partido | último precio | 281 | +13,6 % | −1,9 % | −8,6 % ± 5,8 % |
| total del partido | 6 h antes | 238 | +12,3 % | −2,2 % | +4,1 % ± 6,4 % |
| total del partido | 24 h antes | 78 | +11,8 % | −3,2 % | +10,6 % ± 10,6 % |

El valor que ve el modelo sin calibrar (+10 % a +14 %) es en su mayor parte sesgo y ruido: lo que ocurrió está entre −17 % y +11 %, con errores de ±4 a ±11 puntos. Tomar el mejor precio de las casas compensa solo una parte del margen (el EV según el mercado va de −2 % a −4 %). Con estos datos, **ningún pick de familia es defendible hoy**.

## 7. Un sesgo concreto: el nivel de córners

Observado entre pronosticado, por períodos de 28 días (modelo reconstruido hacia delante, medias del total de córners):

| Período | Partidos | Observado / pronosticado | Córners por partido (observados / pronosticados) |
|---|---:|---:|---:|
| 1 may – 29 may | 1.592 | 0,992 | 9,52 / 9,60 |
| 29 may – 26 jun | 197 | 1,001 | 9,78 / 9,76 |
| 26 jun – 24 jul | 298 | 0,977 | 9,50 / 9,73 |
| 24 jul – 21 ago | 1.037 | 1,011 | 9,69 / 9,59 |
| 21 ago – 18 sep | 1.940 | 1,015 | 9,77 / 9,62 |
| 18 sep – 16 oct | 1.356 | **1,045** | 9,97 / 9,55 |
| 16 oct – 23 oct | 550 | 1,027 | 9,94 / 9,68 |

Desde mediados de septiembre el modelo se queda un 4,5 % corto. Se probó una corrección sencilla, solo como investigación: **multiplicar las medias de cada lado por lo observado entre pronosticado de las 4 semanas anteriores** (solo partidos ya conocidos entonces; con 8 semanas el resultado es casi el mismo). Resultado, comparando con el mercado:

| Mercado | Momento | Partidos | Dijo el modelo | Dijo el mercado | Ocurrió | Log loss modelo | Log loss mercado | Mercado − modelo | Señal extra* |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| total del partido | último precio | 1.268 | 51,1 % | 49,9 % | 52,7 % | 0,6898 | 0,6892 | −0,0006 ± 0,0030 | +0,35 ± 0,27 |
| total del partido | 24 h antes | 785 | 51,7 % | 49,8 % | 55,0 % | 0,6910 | 0,6904 | −0,0006 ± 0,0041 | +0,15 ± 0,34 |
| equipo local | último precio | 1.179 | 49,6 % | 49,9 % | 49,5 % | 0,7039 | 0,6873 | −0,0166 ± 0,0044 | −0,25 ± 0,20 |
| equipo local | 24 h antes | 405 | 49,6 % | 50,0 % | 50,4 % | 0,6958 | 0,6886 | −0,0072 ± 0,0068 | +0,09 ± 0,37 |
| equipo visitante | último precio | 1.181 | 49,7 % | 49,8 % | 52,4 % | 0,6969 | 0,6904 | −0,0065 ± 0,0045 | +0,23 ± 0,19 |
| equipo visitante | 24 h antes | 406 | 50,4 % | 49,9 % | 54,4 % | 0,6933 | 0,6826 | −0,0107 ± 0,0066 | −0,13 ± 0,37 |

Con 8 semanas, en el total: *mercado − modelo* −0,0009 ± 0,0029 al cierre y −0,0020 ± 0,0038 a 24 horas. Es decir, **el total de córners queda a la par del mercado** (antes −0,0040 ± 0,0032), pero **por equipo no se cierra del todo**: el local sigue en −0,017 ± 0,004 al cierre y el visitante pasa de −0,011 a −0,007 ± 0,005 (con 4 semanas). Las apuestas simuladas del total, con la corrección de 4 semanas:

| Mercado | Momento | Apuestas | EV que creía el modelo | EV al probabilidad del mercado | Rendimiento real |
|---|---|---:|---:|---:|---:|
| total del partido | último precio | 672 | +9,7 % | −2,6 % | +1,1 % ± 3,8 % |
| total del partido | 24 h antes | 373 | +9,7 % | −3,8 % | +6,6 % ± 5,0 % |

Rendimientos de +1 % y +7 % con errores de ±4 y ±5 puntos: indistinguibles de cero, y el margen de las casas (≈ −3 %) sigue ahí. Estar a la par del mercado no es tener ventaja.

## 8. Qué significa y qué se propone

1. **Ninguna familia tiene valor demostrado.** Todas siguen en INVESTIGACIÓN y nada de esto llega a una decisión. El criterio del plan (al menos 300 apuestas y CLV no negativo) sigue siendo la puerta para pasar a decidir en sombra.
2. **El primer experimento razonable (F12)** es la corrección de nivel reciente para los totales (córners y, después, tarjetas), con su fila de promoción, y medir una mezcla anclada al mercado (la señal extra del total, de +0,2 a +0,6 con errores de ±0,3 a ±0,6, es un indicio de que el modelo puede aportar algo). Por equipo, el modelo de cada lado tiene que mejorar antes: hoy sabe menos que el mercado, que ve alineaciones, bajas y planteamientos.
3. **Falta tiempo y muestra.** Hay 4 semanas de precios. Desde el despliegue de F10 el servidor guarda pronósticos de las familias antes de cada partido; con ellos se mide sin la aproximación semanal.

**Cómo quedan como hipótesis.** Las dos propuestas del punto 2 (la corrección de nivel reciente y la mezcla anclada al mercado, que depende de la primera) están escritas en el código, `fbi/research/hypotheses.py`, con las cifras de esta guía y la sección de la que sale cada una: una prueba falla si la guía y la propuesta dicen cosas distintas. Para que aparezcan en Evolución, en «Mejoras propuestas», como «Propuesta», se registran con `python -m scripts.hypotheses register --confirm`; sin `--confirm` solo dice cuáles registraría, y `python -m scripts.hypotheses show --full` las lee enteras. Registrarlas no cambia ningún modelo, pronóstico ni pick: las decides tú («Rechazar», «Investigar» o «Aprobar experimento»), y una que ya está registrada no se vuelve a escribir aunque la hayas decidido.

## 9. Cómo se repite

El marcador ya incluye esta comparación para los pronósticos guardados:

```
python -m scripts.families score --days 14            # el marcador y, debajo de cada modelo, «against the market»
python -m scripts.families score --no-market          # sin la comparación con las casas
python -m scripts.families score --min-books 4        # exigir más casas para el consenso (por omisión, 3)
```

El criterio del plan para que una familia decida en sombra (al menos 300 apuestas simuladas y valor de cierre no negativo) lo mide el mismo marcador, debajo de esta comparación, con los pronósticos guardados: ver `CRITERIO_FAMILIAS_F11.md`.

Para probar una idea sobre una familia contra el mercado sin esperar semanas de pronósticos guardados (como la corrección de nivel de la sección 7), está `python -m scripts.families variant`: ver `VARIANTES_VS_MERCADO_F12.md`, que repite la prueba de la sección 7 con la herramienta permanente y la extiende a tarjetas y amarillas.

Solo lee (conexión de solo lectura, 0 peticiones al proveedor, 0 IA). Se califican los partidos jugados en los últimos días, dejando pasar 30 horas (las estadísticas de tarjetas tardan en asentarse). **Las primeras cifras con pronósticos reales saldrán unas dos semanas después del despliegue**; se propone mirarlas cada semana.

## 10. Límites de esta medición

- Ventana de 4 semanas (25-sep a 23-oct): 1.268 partidos con córners totales a su cierre (785 a 24 horas), 410 con tarjetas.
- El modelo es la reconstrucción de F10 con reajuste semanal, no los pronósticos guardados (que se reajustan cada 3 horas y todavía no existen).
- El consenso es proporcional, no el estimador de Shin del resto del sistema; con dos opciones casi equilibradas la diferencia es pequeña.
- El último precio del mercado ya conoce las alineaciones; el modelo no. A 24 horas la comparación es más justa y también la menos precisa.
- Una línea por partido (la principal). Con todas las líneas, los córners dan los mismos signos; las tarjetas, con tan pocos partidos, cambian de signo dentro del error.
- El 25-sep es el principio del reloj de precios; no hay precios anteriores.
- Esta medición se hizo a mano el 24-oct con una herramienta provisional; la herramienta permanente (`score`) la mide por sí misma a partir de ahora, y la prueba de la sección 7 la repite `variant` (`VARIANTES_VS_MERCADO_F12.md`).
