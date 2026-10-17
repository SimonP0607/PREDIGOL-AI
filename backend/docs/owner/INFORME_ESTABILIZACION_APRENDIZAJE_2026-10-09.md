# PREDIGOL — INFORME DE ESTABILIZACIÓN Y APRENDIZAJE (9 oct 2026)

**ESTADO GENERAL:** estable en el servidor (`f021c44` / web `f7f7ea6`, esquema 0075, desplegado a las 18:30 UTC).
Ningún dato se perdió en el corte. Los picks prepartido ya no se pueden reescribir y no desaparecen al empezar el
partido. Cada partido se liquida unos segundos después de terminar. La IA sigue en sombra y ningún modelo ha cambiado.

## 1. Continuidad portátil → servidor

| | |
|---|---|
| Último dato del portátil | 9 oct 03:44:29 UTC (fin de la última pasada de picks) |
| Primer dato del servidor | 9 oct 04:02:39 UTC (captura de cuotas: 9 peticiones, 2.895 cuotas) |
| Huecos | G1, 16 min 39 s (Windows cerró WSL); G2, 17 min 49 s (el corte). No había partidos en juego en ninguno |
| Datos perdidos | **0**: 138 tablas y 51.752.042 / 51.752.042 filas; 84.466 ficheros RAW |
| Recuperados | No hizo falta: el detalle posterior, los cierres prepartido y las pasadas interrumpidas se completaron solos |
| Irrecuperables | **0** por el corte. Hubo 17 ventanas sin captura, ninguna por un hueco: Thai League / ISL por la cobertura del proveedor, Copa del Rey por diseño y 3 en el portátil antes del corte |

Detalle: `VPS_DATA_CONTINUITY_AUDIT_2026-10-09.md`.

## 2. Picks

| | |
|---|---|
| Persistencia después del saque | **Sí.** 484 picks prepartido visibles tras el saque en el primer minuto del despliegue, tal como se tomaron; los del día se pueden consultar hacia atrás |
| Liquidación | Al minuto, por el seguimiento en vivo. La pasada de picks sigue como red de seguridad. Hoy no queda ningún pick abierto en un partido terminado |
| Latencia media de liquidación | **7 s** de mediana y 10 s como máximo (9 partidos, 863 picks; 8 de 8 pasadas completas), desde que se vio el final. Antes: de 3 a 35 min. Durante el despliegue de la 0074, 2 partidos esperaron 18 y 22 min (bloqueo de la migración) |
| Cuotas históricas preservadas | **Sí.** Un trigger impide cambiar la cuota, la hora, las probabilidades o el EV de picks, candidatos, picks del día y piernas de parlay |

## 3. Live

| | |
|---|---|
| Errores detectados | Tres tablas de estados distintas (API, web, «Final» para partidos cancelados o abandonados); SUSP fuera del seguimiento; los picks desaparecían al empezar el partido; el Match Center ocultaba el prepartido; «Pendiente» durante el partido |
| Correcciones | `fbi.core.match_state`, una sola fuente con su espejo en la web: 19 códigos y las mismas reglas de tiempo. Se siguen los suspendidos; «Picks prepartido» en el Match Center; las tarjetas muestran «En juego · minuto · marcador» |
| Estado actual | Verificado en el servidor con partidos reales |

## 4. Caso 9 de octubre

| | |
|---|---|
| Picks estudiados | 5 (todos de `elo_ologit`, todos 1X2) |
| Ganados / Perdidos / Pendientes | 1 / 4 / 0 · −1,30 u |
| CLV | Dos con valor de línea positivo (+5,7 % y +5,1 %), dos neutros (0 %) y uno sin dato del proveedor |
| Errores detectados | Ninguno de ejecución. El #3 era el más débil (un solo modelo contra todos). Las cinco tarjetas no mostraban que la IA las había rebajado |
| Aprendizajes | El modelo sobreestima cuando discrepa del mercado. Los empates de Elo siguen en observación (no es significativo). La cadena de decisión ya se ve en cada tarjeta |

Detalle: `CASO_9_OCTUBRE_2026.md`.

## 5. IA

| | |
|---|---|
| Partidos analizados | 86 hoy (día de Bogotá, hasta las 13:32), 407 llamadas. SELECCIONAR: 866 APROBADO, 516 CAUTELA, 158 RECHAZADO y 0 SIN JUICIO (motor combinado) |
| Post-mortems | 42 de picks y 7 de partidos este mes. Desde hoy, los aciertos se juzgan también: merecidos o con suerte (los primeros, mañana a las 07:35) |
| Hallazgos | La sobreconfianza del modelo: en 8.822 selecciones, el acierto sigue al mercado y no al modelo |
| Patrones bajo observación | Los empates de `elo_ologit` (+7,3 %, ±12 pts) y el sesgo favorito–longshot (1,50–2,19: +2 a +4 %) |
| Hipótesis nuevas | 4 documentadas (H-F17-1/2/3, H-F12-1). El sistema propuso una por sí mismo el 8 oct («Sobreconfianza en cuotas ≥ 3,9: contraer p_model hacia p_close») |

## 6. Ciclo diario

| | |
|---|---|
| Inicio operativo | 00:05 Bogotá (abre el día), con pasadas a 6–4 h del saque y después de las alineaciones |
| Cierre diario | **23:59 Bogotá** (nuevo). Se revisa cada 30 min mientras algo de ese día cambie |
| Último informe | 8 oct, cierre tardío escrito a las 13:08 Bogotá (ese día el cierre aún no existía): completo, 19 partidos, 1-4 en picks del día (−1,10 u) |
| Próximo cierre | Hoy, 9 oct, a las 23:59 Bogotá (04:59 UTC) |

## 7. Odds bands

| | |
|---|---|
| Rangos analizados | 1,20–1,49 · 1,50–1,79 · 1,80–2,19 · 2,20–2,99 · 3,00–4,99 · 5,00+ |
| Muestra | 8.822 selecciones liquidadas (ninguna entre 1,20 y 1,49) |
| Hallazgos | La sobreestimación del modelo es parecida en todos los rangos (+12 a +16 pts). El mercado acierta con una diferencia de 1 a 2,5 pts. ROI: +2,3 % y +4,1 % en los favoritos; −9,7 % de 3,00 a 4,99; −26 % desde 5,00 |
| ¿Conviene especialización? | **No.** El problema es de calibración y es el mismo en todos los rangos. Se propone calibrar hacia el mercado (H-F17-1), no hacer modelos por rango |

## 8. Modelos

| | |
|---|---|
| Cambios automáticos | **0.** Ninguna versión nueva desde las 16:00; la huella sigue en 1f28a883601f |
| Experimentos nuevos | 0 en ejecución. 4 hipótesis documentadas para que decida el dueño |
| Patrones detectados | Sobreconfianza frente al mercado; `elo_ologit` es el único modelo cerca del acierto en 1X2 (+4,2 %) |

## 9. API-Football (día UTC del 9 oct)

| | |
|---|---|
| Peticiones antes (hasta las 15:45) | 7.809 |
| Peticiones utilizadas (durante el programa, hasta las 18:32) | 1.916 |
| Peticiones restantes | 50.197 de 60.000 (16 % usado) |
| Datos recuperados | No hizo falta recuperar nada (§1). La cobertura de la Thai League y la ISL se corrigió sola a las 14:05 |

## 10. Costos de IA

| | |
|---|---|
| Hoy | US$ 3,98 (Bogotá, hasta las 13:32) |
| Mes | US$ 6,55 (desde el 8 oct) |
| Proyección | ~US$ 3,5 al día → **~US$ 100–110 al mes** |
| Presupuesto | US$ 150 (sin alertas) |
| Por unidad | US$ 0,08 por partido analizado; US$ 0,004 por candidato revisado; US$ 0,007 por pick aprobado; US$ 0,0015 por post-mortem; US$ 0,0009 por nota de aprendizaje |

El modelo económico se usa en la rutina (resúmenes, evidencias, post-mortems); el intermedio y el fuerte, solo en
revisiones.

## 11. R2 / backups

| | |
|---|---|
| Estado | **No configurado**: faltan las credenciales del dueño. Hay todo preparado: `deploy/vps/bin/r2-setup.sh` y `r2-restore-drill.sh` |
| Último backup | 9 oct 18:26 UTC, antes del despliegue final (676 MB, en el servidor) |
| Restore test | 9 oct, F0: superado en 408 s en el propio servidor; el chequeo de salud lo sigue dando por bueno. Con R2: pendiente de las credenciales |

## 12. QA

| | |
|---|---|
| Backend | ruff ✓ · mypy estricto ✓ (329 archivos) · `mypy .` ✓ (692 archivos) · pytest **2.033 superados**, 4 omitidos |
| Frontend | lint ✓ (0 errores) · typecheck ✓ · tests **208** ✓ · build ✓ (servidor) |
| E2E | ✓ Ciclo completo de un partido en base real: programado → pick → saque → en vivo → pick visible → final → liquidado → inicio → post-mortem → aprendizaje → cierre del día. La interfaz con sesión no se recorrió en producción (no se introducen contraseñas) |
| Worker | ✓ vivo, un solo worker (código `f021c44`), seguimiento en vivo retomado al minuto, ciclos de IA en verde |
| API | ✓ `/health` OK y endpoints nuevos verificados en el servidor |
| Web | ✓ `/login` OK, imagen `f7f7ea6`; los textos nuevos ya se sirven |

## 13. Problemas encontrados

1. Los picks desaparecían al saque y se volvía a calcular su precio. El Match Center ocultaba el prepartido.
2. La liquidación esperaba a la pasada de picks: hasta ~35 min (Hangzhou: «Pendiente»).
3. Tres vocabularios de estado. Partidos cancelados, abandonados o adjudicados aparecían como «Final». Los
   suspendidos no se seguían.
4. Los partidos que pasan de 90 minutos quedaban pendientes aunque el proveedor diera el marcador a 90 minutos.
5. El tablero de evaluación tiene duplicados: 4.834 tarjetas, 44 % de las versiones duplicadas 258–260, EV
   absurdos. Y el modelo está sobreconfiado.
6. No había valor de línea por pick, ni cierre del día, ni memoria buscable.
7. Los picks del día no decían que la IA los había rebajado.
8. La migración de este despliegue esperó unos 10 min por bloqueos del worker anterior: los 2 partidos que
   terminaron en ese rato se liquidaron 18–22 min tarde.
9. La prueba E2E nueva confirmaba datos fuera de su transacción y rompía la suite completa (57 fallos y 37
   errores). Se corrigió antes del despliegue, junto con 6 errores de tipos antiguos en los tests.

## 14. Correcciones realizadas

`ba645ac`, `4573c15`, `caa2f44`, `2ccb4aa` y `f021c44` (backend), y `f98612a`, `beab2db`, `91f78ce` y `f7f7ea6` (web):

- estado canónico;
- picks inmutables (trigger, 0074) y visibles tras el saque;
- liquidación inmediata con su latencia medida;
- regla settle-v2;
- valor de línea en 15.193 picks;
- cierre del día (0075), con su historial en Admin y la vista «AYER» en Evolución;
- memoria por partido;
- calidad de los aciertos;
- cadena de decisión en cada pick del día;
- navegación por días en Picks, y en Inicio los picks de ayer mientras alguno siga abierto;
- kit de R2;
- documentación del dueño.

## 15. Deuda técnica real restante

1. **Versiones duplicadas 258–260:** no se han borrado, por instrucción. Siguen generando tarjetas del tablero hasta
   que sus partidos pasen (unas 72 h). El dueño decide si se excluyen.
2. **Calibración del modelo frente al mercado** (H-F17-1): requiere experimento y la decisión del dueño.
3. **Explosión de picks por reevaluación:** 100–200 picks por partido, porque cada resultado nuevo reentrena y
   vuelve a evaluar. Las vistas ya lo deduplican; el motor sigue creándolos.
4. **R2 / PITR:** faltan las credenciales del dueño.
5. **E2E de la interfaz con sesión en producción:** necesita que el dueño inicie sesión o una cuenta de prueba
   aprobada.
6. Las migraciones de un despliegue pueden esperar al worker en marcha (aquí, unos 10 min). Habría que añadir un
   `lock_timeout` y reintento en `predigolctl`.
7. **Portátil:** los repos bare tienen todo el código. Las copias de trabajo siguen en `e9ee0c7` / `f7afb0f`,
   porque su base local está en la 0073 y allí no corre ningún worker. `v2_update.sh` queda retirado: arrancaría
   un segundo worker con la misma clave de API-Football.

**SHADOW: ON**
**PICKS LISTOS PARA PUBLICACIÓN: NO** (el modelo está sobreconfiado frente al mercado y la publicación está
bloqueada por diseño)
**DATOS CONFIABLES: SÍ**
**IA APRENDIENDO CORRECTAMENTE: SÍ** (en sombra; los aciertos ahora se juzgan igual que las pérdidas)
**SISTEMA 24/7 ESTABLE: SÍ**

**SIGUIENTE PASO:**

1. El dueño crea el bucket de R2 (`predigol-backups`), un token con lectura y escritura solo en ese bucket y una
   clave `age` (la pública va al servidor, la privada se queda con él). Con eso escribe `/root/r2.env` y se ejecuta
   `r2-setup.sh` y después `r2-restore-drill.sh` (ver §11). Coste estimado: unos US$ 0,20 al mes.
2. El dueño decide sobre H-F17-1 (calibrar hacia el mercado, como experimento) y sobre excluir del tablero las
   versiones 258–260.
