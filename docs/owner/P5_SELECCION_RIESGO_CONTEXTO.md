# P5 — Selección de picks, riesgo, contexto y mercados (REVIEW PREDIGOL, bloque backend)

Datos del servidor del 11 oct 2026 (16:10–16:40 UTC), leídos sin escribir nada. Scripts reproducibles:
`python -m scripts.audit_odds_risk` (riesgo) y las consultas de esta nota. **No se publicó ningún pick, no se tocó
ningún modelo y SHADOW sigue activo.** Lo que cambió es la regla de selección del set del día y de los parlays, con
la evidencia que sigue.

## B1 — «Los picks que estás botando son de cuotas muy altas»

### Lo que hacía la regla (daily-set-v3)

| Día | Picks | Revisados por la IA al elegirse | Cuota media | Máxima |
|---|---:|---:|---:|---:|
| 4 oct | 5 | 0 | 4,43 | 5,00 |
| 5 oct | 5 | 0 | 4,25 | 4,50 |
| 6 oct | 5 | 0 | 3,61 | 4,68 |
| 7 oct | 5 | 0 | 3,62 | 4,20 |
| 8 oct | 5 | 0 | 3,94 | 5,50 |
| 9 oct | 5 | 0 | 3,38 | 4,00 |
| 10 oct | 5 | 0 | 3,20 | 4,16 |
| 11 oct | 5 | 0 | 3,77 | 4,73 |
| 12 oct | 5 | 0 | 2,85 | 4,04 |

Ningún pick del día llevaba una revisión de PrediGol Intelligence al elegirse (10 de 45 tenían una revisión anterior,
pero de más de 12 h; 22 de 45 se revisaron antes del partido, ya elegidos). Solo 5 de los 45 partidos tenían
evidencia externa (noticias): 2 con evidencia «probable» y 5 con «rumor». La observación del dueño es exacta.

### Por qué cuotas altas

La regla ordena por crecimiento esperado con la probabilidad prudente del modelo. Como el modelo está **sobreconfiado**
(auditoría del 9 oct: 12–16 puntos por encima del acierto real en todos los rangos), la diferencia modelo–mercado es
mayor justo en las cuotas altas, y ahí la regla «ve» más valor. Los resultados lo desmienten:

| Cuota tomada | n | Acierto | P. modelo | P. mercado | Rentabilidad (IC 95 %) | Valor de línea |
|---|---:|---:|---:|---:|---|---:|
| 1,50–1,80 | 3.130 | 58,2 % | 71,8 % | 60,1 % | +0,4 % (−5,4 %, +6,2 %) | −2,1 % |
| 1,80–2,20 | 3.229 | 50,1 % | 60,9 % | 49,1 % | +2,8 % (−3,7 %, +10,1 %) | −2,6 % |
| 2,20–3,00 | 4.051 | 36,8 % | 49,4 % | 37,8 % | −3,3 % (−10,0 %, +3,7 %) | −4,1 % |
| **3,00–5,00** | 5.437 | 22,8 % | 34,8 % | 24,1 % | **−13,1 % (−22,4 %, −2,8 %)** | **−8,9 %** |
| 5,00 o más | 267 | 15,7 % | 26,8 % | 17,4 % | −23,8 % (−52,7 %, +12,9 %) | −14,3 % |

16.114 selecciones liquidadas (25 sep – 11 oct), la última evaluación antes del saque de cada selección y familia de
modelo; intervalos por *bootstrap* de partidos. Por la diferencia modelo–mercado no hay un patrón monótono: no se
adopta un tope de diferencia.

### Validación fuera de muestra (rolling walk-forward por día)

Para cada día, el tope de cuota y de diferencia se eligen **solo con los días anteriores** (≥ 1.000 liquidadas) y
ese día se juzga con ellos. Los topes elegidos fueron 2,20 los primeros días y entre 2,50 y 3,00 después — **siempre
≤ 3,00**.

| | n | Acierto | Rentabilidad (IC 95 %) | Valor de línea |
|---|---:|---:|---|---:|
| Todas, sin regla | 14.071 | 38,4 % | −5,7 % (−11,8 %, +1,1 %) | −5,3 % |
| Todas, con el tope del día | 2.563 | 53,1 % | +3,0 % (−4,8 %, +11,7 %) | −1,7 % |
| Set del día (5 por día), sin regla | 36 | 19,4 % | −22,5 % (−69 %, +19 %) | −3,6 % |
| Set del día, con el tope del día | 29 | 51,7 % | +3,2 % (−36 %, +43 %) | −0,6 % |

### Decisión: regla de riesgo `risk-v1` — ninguna cuota por encima de 3,00

Se adopta el tope **menos estricto** que la evidencia respalda: por encima de 3,00 la pérdida es significativa
(el intervalo de −13,1 % excluye el cero) y el valor de línea es el peor; el walk-forward eligió 3,00 o menos todos
los días. **Lo que no se afirma:** que con el tope haya beneficio. La rentabilidad con tope no es significativamente
positiva; la regla evita una pérdida medida, nada más. Se revisará con más días liquidados (`audit_odds_risk`).

### Contexto `context-v1` — todo pick del día pasa por PrediGol Intelligence (desplegado 16:50 UTC)

Un pick del día debe tener una revisión combinada de PrediGol Intelligence de las 12 h anteriores. Se congela con él
lo que la IA leyó: su decisión, su motivo y la evidencia externa del partido por estado. La decisión de la IA solo
cambia la elección cuando está **aplicada** (su propia compuerta en sombra superada): hasta entonces, un
«no recomendado» queda registrado y a la vista del dueño, sin vetar. Con la IA apagada no hay nada que exigir y el
registro lo dice (`ai_off`).

### Hallazgo tras desplegar v4: el set elegía los primeros partidos del día, antes de la IA

Medido en los sets reales del 4 al 12 oct (`picks.daily_set_items` frente a `ai.fixture_passes`):

* 40 de 45 picks se eligieron entre 12 y 24 h antes del partido: en cuanto se abría la ventana de 24 h de los
  primeros partidos del día, la regla llenaba los cinco cupos con ellos.
* 7 de los 20 picks desde el 9 oct eran partidos de las 00:00 de Bogotá, que la pasada del día de la IA (desde las
  00:05) nunca alcanza.
* Desde el 9 oct (cuando empezó la pasada del día de la IA), **ninguno** de los 20 picks tuvo la pasada del día de
  PrediGol Intelligence (paquete, búsqueda de noticias, revisión del modelo) antes de ser elegido: 8 la tuvieron
  después, 7 nunca (los partidos de las 00:00) y los 5 del 12 oct la tendrán después de elegidos; 4 se buscaron en
  la web, todos después. En los 45 desde el 4 oct: 37 sin ninguna pasada y 41 sin búsqueda de noticias.
* La revisión que exigía `context-v1` la cumplía la revisión de reglas gratuita que la IA hace cada 15 minutos; no la
  lectura con noticias que pide el REVIEW. Sus revisiones se renuevan: en 4 días, de 31.970 sondeos cada 30 min
  dentro de las 24 h previas, 205 (0,6 %) encontraron la revisión más nueva con más de 12 h (la revisión solo se
  guarda cuando cambian sus datos): una limitación medida, que solo puede dejar fuera un candidato, nunca meterlo.

### Decisión: `daily-set-v5` con `context-v2` — el pick del día, después de la pasada del día de la IA

* El partido debe tener **su primera pasada del día** terminada (`no_day_pass`): paquete, noticias si le toca,
  resumen y revisión del modelo de los candidatos.
* El set del día se elige **cuando PrediGol Intelligence leyó el día entero**: ninguna primera pasada pendiente, o las
  06:00 de Bogotá como muy tarde (`day_not_ready`). Así los cinco son los mejores del día, no los cinco primeros que
  se leyeron; un partido que empieza antes no puede ser pick del día. Datos reales: la primera pasada cubrió 170
  partidos entre las 00:05 y las 00:46 el 11 oct, y 257 entre las 00:05 y las 04:09 el 10 oct.
* Y, como antes, una revisión combinada de la selección en las 12 h previas (`not_reviewed`).
* Cada pick congela si tuvo la pasada del día (`day_pass`) y si se buscaron sus noticias (`web_searched`).
* **Búsqueda de noticias**: el presupuesto de la web no cambia (20 partidos en la primera pasada, 12 en la previa),
  pero ahora va primero a los candidatos del set en su propio orden (los que pasan el riesgo, por crecimiento
  prudente): los picks del día son los partidos con noticias buscadas.
* **Lo que no se afirma:** que esto mejore el acierto. Es una regla de proceso: todo pick del día lo leyó PrediGol
  Intelligence en su día, con las noticias que encontró.
* Los parlays (`parlay-v5`) y el armador del usuario (`builder-v2`) mantienen `context-v1` (una revisión reciente):
  abarcan días que la IA todavía no abrió.

### Versiones

`daily-set-v5` (picks del día; `daily-set-v4` rigió desde las 16:50 UTC del 11 oct sin llegar a elegir ningún pick:
los sets del 11 y del 12 ya estaban completos con v3), `parlay-v5` (parlays de PrediGol: riesgo y `context-v1` en
cada pierna) y `builder-v2` (el armador del usuario hereda parlay-v5). Los registros anteriores conservan su versión.

### Verificación con datos reales (v4 desplegado, 11 oct, 16:51 UTC)

* Embudo (vista previa, 2,85 s): 921 selecciones de las próximas 24 h → datos 828 (93 a menos de 10 min) → mercado
  667 (157 precio viejo, 4 pocas casas) → modelo y calibración 667 → valor 85 (559 sin crecimiento prudente, 23 sin
  VE) → **riesgo 40 (45 por encima de 3,00)** → IA 40 → selección 0 (sets llenos). Calificados: 0 (ningún modelo).
* Armador (dueño, 24 h, 2–4): 654 con valor → **424 bajo el tope** → 52 revisados → 36 combinables en 21 partidos;
  piernas a 2,10 / 2,55 / 2,47 / 2,55 (antes 4,01 / 4,84 / 4,00). Usuario: sin candidatos (sin modelo calificado).
* La web desplegada contiene el embudo (`/admin/picks/funnel` responde 401 sin sesión, como debe).

### Embudo trazable

`GET /api/v1/admin/picks/funnel` (Admin → Picks → «Embudo de selección»): datos → mercado → modelo → calibración →
valor → riesgo → PrediGol Intelligence → selección, con cuántos entran y pasan en cada paso, por qué se queda cada
uno, qué entraría ahora y qué casi entra; si la IA ya leyó el día y, por candidato, su pasada del día y su búsqueda
de noticias. Se calcula con las mismas funciones que el set del día (un test lo comprueba). El usuario ve la misma
cadena en «Cómo llega un pick del día», sin nombres de modelos.

## B4 — IA objetiva con contexto: clases de evidencia

Ya existían y las decide el servidor, nunca un modelo (`fbi.ai.evidence`):

* **CONFIRMED** (confirmada): fuente oficial (federación, liga, club) con fecha, alineación confirmada, o dos medios
  independientes que dicen lo mismo.
* **PROBABLE**: un medio o periodista, o el parte del proveedor de datos.
* **RUMOR**: agregador, red social o sitio desconocido, solo.
* **CONTRADICTORY** (contradictoria): fuentes de nivel comparable que no coinciden.
* **OUTDATED** (desactualizada): superada por algo más nuevo o demasiado vieja.

«Sin evidencia» es la ausencia de filas. P5 congela este conteo en cada pick del día y lo muestra en el embudo.

## Post-mortems de aciertos y fallos

Existían (`pm-v2`). Últimos 7 días:

* Aprobados: 111 ganados y 155 perdidos.
* Con cautela: 95 ganados y 146 perdidos.
* Rechazados: 28 habrían ganado y 53 fueron rechazos correctos.
* Sin revisión: 12 ganados y 21 perdidos.
* Empates/devoluciones: 14.

Cada acierto se juzga como un fallo: si se «ganó» o fue «suerte», frente al cierre.

## B3 — Más mercados: auditoría (nada se activa sin backtest)

259 partidos con cuotas prepartido leídas de RAW (últimas 36 h). Columnas: partidos cotizados, casas (media y mediana)
y datos para liquidar (estadísticas de API-Football desde el 1 jul 2025, 30.288 partidos).

| Mercado (bet del proveedor) | Partidos | Casas (media / mediana) | Datos para liquidar | Veredicto |
|---|---:|---|---|---|
| Goles por equipo (16, 17) | 259 (100 %) | 6,7 / 7 | marcador (100 %) | **1.ª prioridad**: los modelos de goles ya dan λ por equipo; falta backtest |
| Córners O/U (45) | 245 (95 %) | 4,8 / 5 | córners 87,5 % | **2.ª prioridad**: líquido y liquidable; falta modelo de córners y backtest |
| Hándicap de córners (56), córners por equipo (57, 58) | 238 (92 %) | 4,4–4,5 / 5 | 87,5 % | con el anterior |
| Tarjetas O/U (80) | 131 (51 %) | 2,3 / 3 | amarillas 86,6 % | 3.ª: mitad de los partidos, liquidez justa |
| Remates al arco totales (87) | 103 (40 %) | 1,7 / 1 | 87,5 % | no viable: una casa (sin consenso) |
| Remates totales (211) | 102 (39 %) | 1,9 / 1 | 87,0 % | no viable |
| Paradas del portero (267) | 71 (27 %) | 1,4 / 1 | paradas 85,7 % | no viable |

Hoy se normalizan 1X2, OU, BTTS, AH y DC (≈ 985 partidos en 30 días); el resto queda guardado en RAW, de donde se
puede reconstruir el histórico de precios para un backtest. Plan, en orden y sin activar nada:

1. Goles por equipo: normalizar las cuotas desde RAW.
2. Goles por equipo: predicciones *walk-forward* con los modelos de goles existentes.
3. Goles por equipo: backtest frente al mercado sin margen (log loss, rentabilidad, valor de línea).
4. Goles por equipo: 30 días en sombra.
5. Goles por equipo: decisión del dueño.
6. Córners: el mismo camino, más un modelo nuevo (Poisson / binomial negativa con córners a favor y en contra).
