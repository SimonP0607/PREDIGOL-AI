# ¿Se pueden publicar picks? — decisión del 5 oct 2026

**PICKS_READY_FOR_USERS = NO · KEEP_SHADOW = YES**

Ningún modelo de PrediGol supera hoy al mercado sin margen, ni le aporta información. Los picks siguen en *shadow*
(se registran y se liquidan, nadie los ve) y la publicación sigue desactivada por una restricción de la base de datos.
No se ha relajado ninguna regla para "tener algo que enseñar".

Todo lo de este documento se puede rehacer con dos comandos, sin pedir nada al proveedor:

```
python -m scripts.research_v2              # investigación V2 en seco: no guarda nada (5 oct, 07:55 UTC, 10,3 min)
python -m scripts.shadow_evaluation        # picks shadow: ROI con intervalos por partido, CLV, calibración (08:26 UTC)
```

| Evidencia | Archivo (en la máquina) | Código |
|---|---|---|
| Investigación V2 (walk-forward, 5 grandes ligas, temporada de prueba 2024/25) | `data/reports/research-v2-2024-20261005T075534Z.md` y `.json` | `27038b9f` |
| Evaluación de los picks shadow | `data/evaluation/20261005T082651Z/shadow_evaluation.json` | `c752206` |
| Conjunto de datos | `DATASET_V2` reconstruido 5 oct 08:14 UTC: **VALIDATED**, todas las puertas *pass* o *note* | `data/truth/20261005T081446Z-datasets/` |

## 1. Por qué la respuesta es NO

1. **Ningún modelo gana al mercado en la temporada de prueba.** Sobre 1.751 partidos (Premier League, LaLiga,
   Bundesliga, Serie A, Ligue 1, 2024/25) el mejor pronóstico es el propio mercado: Pinnacle al cierre sin margen
   (método *power*), log loss **0,95967**. Los 8 modelos quedan por detrás y el intervalo del 95 % de la diferencia
   está entero por encima de cero (peor):

   | Modelo | Log loss | Diferencia con el mercado [IC 95 %] | Peso en una mezcla con el mercado [IC 95 %] | Rol |
   |---|---:|---|---|---|
   | Ensamble (pool de 5) | 0,97928 | +0,0182 [+0,0105, +0,0261] | −0,197 [−0,507, +0,084] | RECHAZADO |
   | Logit multinomial | 0,98176 | +0,0210 [+0,0127, +0,0290] | −0,206 [−0,467, +0,060] | RECHAZADO |
   | Elo + logit ordenado | 0,98619 | +0,0256 [+0,0177, +0,0336] | −0,266 [−0,530, −0,034] | RECHAZADO |
   | Poisson | 0,98708 | +0,0261 [+0,0170, +0,0353] | −0,213 [−0,454, +0,019] | RECHAZADO |
   | Dixon-Coles | 0,98708 | +0,0262 [+0,0173, +0,0356] | −0,224 [−0,480, +0,012] | RECHAZADO |
   | Gradient boosting | 0,99663 | +0,0358 [+0,0217, +0,0498] | +0,056 [−0,118, +0,228] | RECHAZADO |
   | Gradient boosting + mercado | 1,02370 | +0,0640 [+0,0437, +0,0836] | +0,052 [−0,065, +0,187] | RECHAZADO |
   | Tasas base | 1,07975 | +0,1193 [+0,1016, +0,1379] | −0,102 [−0,210, +0,019] | RECHAZADO |

   Un peso positivo con su intervalo por encima de 0 querría decir "el modelo añade algo al mercado". No ocurre en
   ningún modelo; la mezcla ajustada en validación tampoco mejora al mercado en prueba (todas las diferencias, entre
   −0,0009 y 0,0000, con intervalos que cruzan el cero).

2. **Los picks shadow no tienen ventaja medible.** 4.070 picks liquidados sobre **181 partidos** (25 sep – 5 oct):

   | Medida | Valor | Lectura |
   |---|---|---|
   | ROI | +5,5 %, IC 95 % por partido **[−16,9 %, +26,9 %]** | indistinguible de la suerte: el intervalo contiene el 0 y el −5 % de margen típico |
   | VE que prometía el modelo | +29,2 % | sobreconfianza: el modelo cree ver ventajas que no existen |
   | VE frente al consenso sin margen en el momento del pick | **−4,6 % ± 0,4 %** | el precio tomado era, para el mercado, una apuesta perdedora |
   | VE frente al cierre de Pinnacle **sin margen** (2.923 picks, 157 partidos) | **−1,0 % [−2,1 %, +0,0 %]** | ni el cierre "afilado" da la razón a los picks |
   | Cociente bruto frente al último precio de Pinnacle | +4,7 % de media | **no es CLV**: compara la mejor de 9 casas con una casa que conserva su margen |
   | Fiabilidad de la ventaja (λ en y − q = λ·(p − q)) | 0,44 [−0,29, +1,01] | no se distingue de 0 (el mercado tenía razón) |
   | Calibración (1X2) | modelo 38,8 % · mercado 30,6 % · real 28,4 % | el mercado acierta; el modelo exagera |

   Por mercado (VE frente al cierre de Pinnacle sin margen): 1X2 −1,6 % [−2,9 %, −0,3 %], hándicap asiático
   −0,3 % [−1,9 %, +1,3 %], más/menos −1,5 % [−3,1 %, +0,1 %]. Los picks tomados al propio precio de Pinnacle
   −2,5 % [−3,7 %, −1,2 %]: su cierre se movió en contra.

3. **Modelos calificados: 0.** Para calificar, la versión exacta del modelo debe haber batido al mercado sin margen en
   su propio backtest y sostenerlo de forma prospectiva. Ninguna lo hace.
4. **El conjunto de datos no está promovido.** `DATASET_V2` es VALIDATED; pasar a MODEL_READY es una decisión del
   dueño (ver §4). Mientras tanto la investigación está congelada: ninguna ejecución guarda modelos nuevos.

## 2. Qué es el backtesting (y qué no es)

**Qué es.** Volver al pasado y hacer, partido a partido, exactamente lo que el sistema habría hecho en ese momento,
con lo que se sabía en ese momento, y comparar el resultado con lo que pasó y con lo que decía el mercado.

```
Entrenamiento ─► Validación ─► Corte temporal ─► Predicción ─► Precio disponible ─► Resultado ─► Comparación con el mercado
 (2 años hasta    (2023/24:      (60 min antes      (probab.     (cuota capturada     (90 min)     (log loss, Brier,
  el corte)        elegir         del primer         del modelo)  antes del inicio)                 calibración, VE, CLV)
                   hiperparám.)   partido del bloque)
```

* **Walk-forward**: el modelo se reentrena cada día de la temporada de prueba solo con los partidos cuyo resultado era
  público 3 h después de su inicio y antes del corte; nunca ve un resultado futuro.
* **Fuga de información (leakage)**: usar algo que no se sabía al predecir (el resultado, la cuota de cierre, una
  alineación posterior). El protocolo la impide por construcción: cada bloque comprueba que ningún dato de
  entrenamiento es posterior al corte, y una prueba reescribe todos los resultados futuros y exige predicciones
  idénticas.
* **Calibración**: si el modelo dice 60 %, debe ocurrir ~60 % de las veces. *ECE* mide cuánto se aleja.
* **Brier y log loss**: penalizan la distancia entre la probabilidad dada y lo que pasó. El log loss castiga mucho la
  seguridad equivocada. Menor es mejor; se comparan siempre **en los mismos partidos**.
* **Línea base de Pinnacle**: la cuota de cierre de una casa "afilada", sin su margen (Shin, proporcional o *power*),
  es el pronóstico público más difícil de batir. Es la vara de medir, no un modelo nuestro.
* **ROI y VE**: el ROI es lo que se ganó por unidad apostada; el VE (valor esperado) es lo que se *debería* ganar si
  la probabilidad usada fuera la verdadera. Un VE alto con un modelo mal calibrado no vale nada.
* **Intervalos de confianza**: se calculan remuestreando **partidos** (o jornadas), no picks: diez líneas de un mismo
  partido ganan o pierden juntas y cuentan como una observación.

**Qué NO es.** No es una promesa de beneficios, no es un historial de apuestas reales (no se ha apostado dinero), y no
demuestra nada con pocas muestras: con 181 partidos, un ROI del +5,5 % tiene un intervalo de ±22 puntos; hace falta
del orden de miles de partidos para distinguir una ventaja de 1-2 % de la suerte. **Un ROI alto en una muestra pequeña
no prueba nada; un modelo que no gana en log loss al mercado sin margen no tiene ventaja, gane lo que gane una semana.**

## 3. Descomposición del error (por qué los modelos pierden)

| Fuente | Diagnóstico con evidencia | Peso |
|---|---|---|
| DATOS | Dataset auditado: 0 críticos, 0 altos propios; 3 payloads RAW dañados el 4 oct (40 filas, registrados, causa corregida: fsync antes de renombrar) | bajo |
| FEATURES | Solo goles, Elo, forma y tiros agregados: la misma información que el mercado ya incorpora; sin xG, sin alineaciones confirmadas, sin lesiones fiables | **alto** |
| MODELO | Las familias (Poisson, Dixon-Coles, Elo, GBM) están en el rango de la literatura (RPS ~0,005–0,014 peor que las cuotas) | medio |
| CALIBRACIÓN | Sobreconfianza en lo seleccionado: VE prometido +29 % frente a −4,6 % real; ECE 0,7–5,4 % | **alto** |
| SELECCIÓN DE MERCADO | Elegir las mayores diferencias con el mercado elige los errores del modelo (*optimizer's curse*) | **alto** |
| MOMENTO DE LA CUOTA | Precios capturados en ventanas T-72 h…T-3 h; el cierre se mueve poco (+0,1 %): no explica la pérdida | bajo |
| MEZCLA DE LIGAS | Shadow: muchas ligas menores y selecciones juveniles; prueba histórica: solo 5 grandes ligas | medio |
| MUESTRA | 181 partidos shadow, 8 días: insuficiente para cualquier conclusión positiva | **alto** |
| RÉGIMEN | Temporada 2026/27 recién empezada (pocos partidos por equipo) | medio |

## 4. Qué haría falta para pasar a YES (sin bajar ninguna regla)

1. El dueño revisa `DATASET_V2` (puertas en `data/truth/20261005T081446Z-datasets/`), retira `data/research.frozen`
   y lo promueve: `python -m scripts.dataset_version promote --name DATASET_V2 --by NOMBRE --confirm`.
2. Investigación V2 con `--apply` (queda sellada con la versión del código de modelos y del dataset).
3. Experimentos, en este orden (literatura revisada el 5 oct 2026; ver `docs/research/MODEL_RESEARCH_V2_2026.md`):

   | # | Experimento | Pasa si | Esfuerzo |
   |---|---|---|---|
   | 1 | Mezcla con el cierre: log π = a + α·log q + β·log p | IC 95 % de β > 0 **y** ΔLL(mezcla − cierre) con IC < 0, por jornadas | horas |
   | 2 | Fiabilidad de la ventaja λ en los picks | IC de λ excluye 0 con ≥ 500 picks | horas |
   | 3 | Auditoría CLV sin margen (ya medida aquí: −1,0 %) | media > 0 con IC por jornada sobre ≥ 300 partidos | días |
   | 4 | xG / tiros en lugar de goles | criterios del 1 en ≥ 2 temporadas seguidas, 1X2 y más/menos 2,5 | 1–2 semanas |
   | 5 | Fuerza de la alineación confirmada (T-60) | β > 0 y CLV positivo de T-60 al cierre en ≥ 300 partidos | semanas |

4. Un modelo solo se promueve si pasa la puerta frente al mercado **y** el dueño lo aprueba explícitamente. Nada de
   esto lo hace una IA ni ocurre solo.

| Fuente principal de la literatura | Hallazgo |
|---|---|
| Hvattum & Arntzen 2010 (IJF) | Elo + logit ordenado, significativamente peor que las cuotas |
| Baboota & Kaur 2019 (IJF) | GBM RPS 0,2156 frente a Bet365/Pinnacle 0,2012 |
| Flepp 2024 (Economic Inquiry) | los precios de cierre infravaloran el xG: única evidencia revisada por pares de información no incorporada |
| Wheatcroft 2020 (IJF) | ratings de tiros > goles; beneficio solo a la cuota **máxima**, pérdida a la media |
| Holmes & McHale 2024 (IJF) | ratings de jugadores: Brier peor que Bet365 aunque con ROI variable |
| Angelini & De Angelis 2019 (IJF); Hegarty & Whelan 2025 (IJF) | mercados eficientes en 8 de 11 ligas; el hándicap asiático, eficiente |
| Wunderlich & Memmert 2020 (IJF) | el rendimiento de apuestas no es una medida válida de precisión |
| Smith & Winkler 2006 (Management Science) | *optimizer's curse*: seleccionar las mayores ventajas selecciona errores |
