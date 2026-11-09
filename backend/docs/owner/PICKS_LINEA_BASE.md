# PICKS: línea base y liquidación recalculada (plan PICKS, F1 y F6)

Dos lecturas de solo lectura para medir el punto de partida del módulo PICKS y comprobar lo ya liquidado. Ninguna escribe en la base: la conexión la abre el servidor en modo `READ ONLY` y cualquier `INSERT` o `UPDATE` falla. No llaman al proveedor.

Las cifras de este documento se rellenan **con la corrida en producción**. Hasta entonces, las secciones de resultados dicen «pendiente» y no se adelanta ningún número.

## Cómo se corren

En el servidor, dentro del contenedor del worker, como las demás herramientas de las guías. Usa la conexión del worker, pero cada herramienta la abre en solo lectura:

```
docker exec -w /app predigol-worker python -m scripts.audit_picks_module --hours 24                  # línea base (F1)
docker exec -w /app predigol-worker python -m scripts.audit_picks_module --hours 24 --json > picks_f1.json
docker exec -w /app predigol-worker python -m scripts.audit_settlement --days 30                     # liquidación recalculada (F6)
docker exec -w /app predigol-worker python -m scripts.audit_settlement --days 30 --json > picks_f6.json
```

El `> archivo.json` guarda el resultado en la carpeta del servidor desde la que se lanza, fuera del contenedor. Las herramientas existen en el servidor desde el despliegue que incluye BE-007.

`audit_settlement` termina con código 1 si encuentra un cambio sin explicar o un día cuyo resumen no cuadra, y con 0 si todo cuadra.

## Llave de solo lectura para las auditorías

Para que Claude (u otra persona) lance estas herramientas sin tener la llave de root, hay una llave aparte que solo puede hacer eso. Su orden forzada, `predigol-audits` (en el repositorio: `backend/deploy/release/templates/gate/predigol-audits`), acepta solo:

```
audit_picks_module [--hours N] [--json]              N de 1 a 168
audit_settlement [--days N] [--no-timing] [--json]   N de 1 a 90
research_picks_calibration [--days N] [--json]       N de 1 a 400
help
```

Cualquier otra cosa se rechaza: una consola, otro script, `;`, `|`, `$( )`, una ruta o una opción que la herramienta no tiene. Cada llamada, permitida o rechazada, queda en `/var/log/predigol-audits.log` con la dirección del cliente. `restrict` quita además la terminal, los reenvíos y el agente.

**Instalarla (una vez, como root en el servidor):**

1. Copiar la orden forzada: `install -m 755 -o root -g root predigol-audits /usr/local/sbin/predigol-audits`.
2. Añadir a `/root/.ssh/authorized_keys` una línea con la llave **pública** nueva (nunca la privada):
   `command="/usr/local/sbin/predigol-audits",restrict ssh-ed25519 AAAA… predigol-audits`
3. Probar desde el equipo que tiene la llave: `ssh predigol-audits help` debe listar las tres herramientas, y `ssh predigol-audits id` debe responder `refused`.

**Quitarla:** borrar esa línea de `authorized_keys`. La llave de root y la del despliegue no se tocan.

## Qué mide `audit_picks_module` (F1)

Llama a los mismos servicios que responde la API en la vista previa del dueño (`picks_board`, `started_board` y `daily_board`), así que cuenta lo mismo que se ve en pantalla:

| Hallazgo | Qué cuenta |
| --- | --- |
| Motor | Precios evaluados, picks en sombra, calificados, publicados (deben ser 0) y liquidados |
| S1 | Tarjetas que hoy no pasan la regla de valor, y por qué (precio viejo, partido no programado, pocas casas, VE no positivo) |
| S2 | Tarjetas que repiten la misma idea en otra línea (mismo partido, mercado y lado); tarjetas por partido: mediana y máximo |
| S3 | Tarjetas con cuota por encima de 3,00 |
| C4 | En goles, «menos de» frente a «más de»; en ambos marcan, «no» frente a «sí» |
| C5 | Edad del precio de cada tarjeta: menos de 1 h, de 1 a 3 h, más de 3 h, sin precio; y la del más nuevo |
| L2 | «Ya empezaron hoy»: candidatos, partidos y el máximo en un partido |
| D1 | Los dos «picks del día»: el de la página (con su regla y sus estados) e Intelligence (último estado de cada selección del día de Bogotá y su set) |

## Qué mide `audit_settlement` (F6)

Para cada registro liquidado sobre un marcador de los partidos de los últimos N días (picks en sombra, picks del día, patas de las combinadas de PrediGol, picks y combinadas de los lectores), lo vuelve a liquidar con las mismas reglas (`settle-v4`) y la misma lectura que la reliquidación, y lo compara con lo guardado:

| Resultado | Significado |
| --- | --- |
| Igual | Lo guardado es lo que dan hoy las reglas |
| Retenido | Una diferencia que las reglas dejan a una persona: un nulo por regla, o un partido que ya no se liquida |
| Cambio con corrección registrada | El resultado del partido se corrigió después de liquidarse el registro y la reliquidación aún no lo aplicó. Una corrección anterior a la liquidación no explica nada: ya debía estar en lo guardado |
| **Sin explicar** | El criterio del plan es **cero** |

Después comprueba en los datos que el resumen de cada día cuadra (ganados + perdidos + nulos o devueltos + por jugar = tamaño del set) y mide cuánto tardan las dos consultas de la consola de rendimiento (R1). La base ya impide un estado fuera de esa lista, así que hoy esa suma no puede fallar: queda como guarda por si algún día se añade un estado. Lo que sí puede fallar es la liquidación de cada pick del día, y esa se comprueba arriba, registro a registro.

Si aparece algo sin explicar, **no se corrige desde aquí**: se usa la reliquidación (`docker exec -w /app predigol-worker python -m scripts.resettle`), que deja rastro, con tu visto bueno.

## Misma probabilidad para la misma selección (F3)

Antes de encender `FBI_PICKS_SOURCE=intelligence` hay que comprobar, fila a fila, que un lector ve el mismo número en Picks y en el Match Center. `compare_probabilities` es de solo lectura (la conexión la abre el servidor en `READ ONLY`, con dos minutos de límite), no llama al proveedor y no cambia nada:

```
docker exec -w /app predigol-worker python -m scripts.compare_probabilities --hours 24 --top 15
docker exec -w /app predigol-worker python -m scripts.compare_probabilities --hours 72 --json > picks_f3.json
```

Para cada selección (partido, mercado, lado y línea) de la ventana pone lado a lado cuatro lecturas: la cruda del motor de picks (lo que mostraba el tablero antes de F3), la del tablero con el interruptor, la calibrada de Intelligence (`decision-v1`, último punto de control) y la del pronóstico del Match Center (`forecast-v1`). De cada par da cuántas selecciones se comparan, la mediana, el percentil 90 y el máximo de la diferencia en puntos, y cuántas pasan de 0,5 puntos. También cuenta de qué punto de control viene cada lectura de Intelligence y qué edad tiene (el momento de referencia) y lista las diferencias más anchas entre el Match Center y el tablero.

El veredicto **SE CUMPLE** solo si hay selecciones comparables y no hay ninguna diferencia de más de 0,5 puntos entre el tablero con el interruptor e Intelligence, ni entre el Match Center y el tablero. Si no hay lecturas de Intelligence todavía, dice que no hay selecciones comparables: no es un cumplimiento. **No se enciende el interruptor mientras el veredicto sea «NO SE CUMPLE» o «no comparables».**

## Resultados

Corrida del 9-nov-2026, 00:50 UTC (19:50 del 8-nov en Bogotá), con la llave de solo lectura (SEG-002).

### Línea base (F1), ventana de 24 h

| Hallazgo | Cifra |
| --- | --- |
| Motor | 2.330.675 precios evaluados · 337.227 picks en sombra · 0 calificados · 0 publicados · 335.103 liquidados |
| Tablero | 155 tarjetas de 15 partidos (de noche: menos partidos que en la lectura del 7-nov) |
| S1 fuera de la regla ahora | 91 (59 %): 82 por precio viejo y 9 por VE no positivo |
| S2 misma idea en otra línea | 107 (69 %); por partido, mediana 10 y máximo 24 |
| S3 por encima de 3,00 | 55 (35 %) |
| C4 dirección | goles: 42 «menos de» frente a 9 «más de» (82 %); ambos marcan: 6 «no» frente a 0 «sí» |
| C5 edad del precio | menos de 1 h: 20 · de 1 a 3 h: 53 · más de 3 h: 82 (53 %) · el más nuevo, hace 17 min |
| L2 «Ya empezaron» | 2.701 candidatos de 206 partidos; hasta 22 en uno |
| D1 picks del día de la página | `daily-set-v5`: 5 picks del 8-nov, los 5 perdidos |
| D1 Intelligence (día de Bogotá) | 2.722 selecciones: 0 aprobadas, 40 en cautela, 6 en investigación, 2.676 rechazadas; su set del día, vacío |

### Liquidación recalculada (F6), 30 días

3.804 partidos (28 con correcciones registradas del resultado).

| Registro | Examinados | Iguales | Retenidos | Con corrección | **Sin explicar** |
| --- | --- | --- | --- | --- | --- |
| Picks en sombra | 313.714 | 312.612 | 946 (nulos por regla que se mantienen) | 0 | **156** |
| Picks del día | 146 | 145 | 0 | 0 | **1** |
| Patas de combinadas | 243 | 243 | 0 | 0 | 0 |
| Picks de lectores | 0 | 0 | 0 | 0 | 0 |
| Patas de combinadas de lectores | 52 | 52 | 0 | 0 | 0 |

Los 30 sets del día cuadran.

**El criterio (0 sin explicar) no se cumple.** 157 registros están liquidados con un marcador distinto del que hoy tiene su partido, y ninguna corrección registrada lo explica:

- 101 son de partidos del 10 al 12 de octubre. Los 20 que muestra la herramienta son todos de Gwangju FC 4–3 Ulsan Hyundai (K League 1, 11-oct, partido 21562): están liquidados como si hubiera acabado en empate con dos goles o menos («empate» ganado, «menos de 2,5» ganado, «local» perdido). También es de ese partido el pick del día n.º 2 del set 8, guardado como perdido cuando hoy sería ganado.
- 55 son de partidos de los últimos 27 días; entre ellos, los partidos 21497 y 21389.

**Causa (9-nov, solo lectura).** Todos son de partidos anteriores al 24-oct, es decir, de antes de que existiera el rastro de correcciones (migración 0080, 23-oct): hasta entonces el resultado se sobrescribía en el sitio y la liquidación corría con la primera lectura de «final», sin dejar nada en `core.fixture_result_revisions`. La misma auditoría con `--days 16` da **0 sin explicar** sobre 181.164 picks, 76 picks del día y 122 patas de combinadas (2.198 partidos, 22 con correcciones registradas), y los sets del día cuadran. No es un defecto nuevo ni sigue creciendo.

### Reliquidación de los 157 (F6), aplicada el 9-nov-2026

Con el visto bueno del dueño y en este orden:

1. **Simulacro** (`scripts.resettle --all`, sin `--apply`, que escribe dentro de una transacción que se revierte): 157 registros de 3 partidos (21562 Gwangju FC 4–3 Ulsan Hyundai, 21497 Debreceni 3–0 Zalaegerszegi, 21389 Barcelona SC 1–1 U. Católica) y 1.027 retenidos para una persona (todos nulos «por regla» que se mantienen: no se tocaron).
2. **Verificación aparte** de las 156 de picks en sombra: cada una se recalculó fuera de la herramienta con el marcador que dan los eventos de gol de su partido (127 de goles, 20 de 1X2, 9 de hándicap asiático). Las 156 coinciden con lo que proponía la herramienta; 0 discrepancias. El pick del día restante (partido 21562) pasa de pérdida a acierto, en línea con el 4–3; no se recalculó aparte.
3. **Copia de seguridad y prueba de restauración** antes de escribir: `predigol-20261109T152018Z-pre-resettle-20261109`, restauración aprobada en 1.600 s. Marcha atrás: restaurar esa copia; el rastro queda en `picks.resettlements` con el motivo «manual run by Simon».
4. **Aplicado** con `--apply --by Simon`: 157 registros, 3 partidos, 0 conflictos.
5. **Comprobación posterior**: el simulacro vuelve a dar 0 cambios y `audit_settlement --days 30` da **0 sin explicar** (295.451 picks examinados, 142 picks del día, 237 patas de combinadas, 52 patas de lectores; los 31 sets del día cuadran).

Lo derivado no se reescribe, se conserva con su historial y se reconstruye en F8: `ai.pick_postmortems` 4, `ai.postmortems` 3, `intel.decision_outcomes` 64, `intel.match_postmortems` 3, `intel.postmortems` 4. Los 1.027 retenidos siguen esperando a una persona.

### Consola de rendimiento (R1)

Totales: 3,3 s · porciones: 7,0 s, corriendo a la vez que las otras dos auditorías. La consola responde desde BE-006, y el navegador la midió en 11,2 s el 8-nov.

### Peso de las respuestas (U5), medido el 9-nov-2026

Medido con los mismos servicios que responden a la API (JSON con alias, en solo lectura), sobre la vista previa del dueño de las próximas 24 h:

| Respuesta | Tamaño | Elementos | Por elemento | Página de 15 |
| --- | --- | --- | --- | --- |
| Tablero de evaluación | 193,8 KB | 171 tarjetas | 1,16 KB | 17,0 KB |
| «Ya empezaron» (evaluación) | 37,2 KB | 32 | 1,19 KB | 17,4 KB |
| Pick del día (evaluación) | 14,3 KB | 5 | 2,93 KB | 42,9 KB |

El criterio del plan (menos de 300 KB por página) se cumple incluso pidiendo el tablero entero (el 7-nov pesaba 4,9 MB; bajó con la regla de valor y la antigüedad del precio). El margen es de unas 258 tarjetas: **no hace falta paginar en el servidor ahora**; hay que volver a medir en un día de mucha carga. Es una sola medición, a una hora concreta, y no cuenta la compresión del servidor web.

### Sesgo de goles (Q2), medido el 9-nov-2026

Poisson, «más de 2,5», último pronóstico antes del inicio, partidos terminados de octubre y noviembre de 2026:

| Lectura | Partidos | Probabilidad media | Frecuencia real de «más de 2,5» |
| --- | --- | --- | --- |
| Pronóstico del producto (`forecast-v1`, calibrado por el campeón) | 2.029 | 57,2 % | 55,9 % |
| El mismo modelo sin calibrar (`p_model`) | 2.029 | 52,3 % | 55,9 % |
| Sin calibrar (pronóstico marcado «sin calibrar») | 114 | 54,9 % | 61,4 % |

El sesgo hacia pocos goles está en la probabilidad **cruda** (−3,6 puntos en «más de»), que es lo que el tablero usaba antes de F3. El pronóstico calibrado que ve el producto queda a +1,3 puntos del real: del orden de un error estándar de la muestra (1,1 puntos), por lo que no hay evidencia de un sesgo que corregir allí. **Conclusión: no se toca ningún modelo.** Si se quisiera corregir la cruda en su origen (un factor sobre el total de goles esperado), sería un candidato nuevo en la línea de modelos y tendría que superar su propia puerta estadística antes de promoverse.

### Misma probabilidad para la misma selección (F3), medida en producción el 9-nov-2026

Corrida de las 18:39 UTC con `compare_probabilities` de solo lectura. El lote desplegado ese día (`62d46780`) es anterior a la herramienta, así que se copió el archivo a `/tmp` del contenedor del worker y se ejecutó desde allí (solo importa la biblioteca estándar, `psycopg` y la configuración; no tocó la imagen, el código desplegado ni los datos).

Diferencia, en puntos, entre dos lecturas de la misma selección:

| Par | Ventana | Selecciones | Mediana | p90 | Máximo | Por encima de 0,5 pp |
| --- | --- | --- | --- | --- | --- | --- |
| Tablero (cruda) / Intelligence | 24 h | 150 | 9,4 | 17,6 | 53,2 | 150 (100 %) |
| Tablero (cruda) / Intelligence | 72 h | 206 | 9,5 | 19,3 | 53,2 | 206 (100 %) |
| Tablero (con el interruptor) / Intelligence | 24 h y 72 h | 150 y 206 | 0,0 | 0,0 | 0,0 | 0 |
| Match Center / Intelligence | 24 h | 25 | 2,3 | 3,8 | 4,1 | 20 (80 %) |
| Match Center / Intelligence | 72 h | 73 | 4,8 | 15,2 | 26,6 | 66 (90 %) |
| Match Center / tablero (con el interruptor) | 72 h | 90 | 4,2 | 15,2 | 26,6 | 80 (89 %) |

**Veredicto: NO SE CUMPLE.** Con el interruptor, el tablero y Intelligence coinciden en todas las selecciones (0 diferencias de más de 0,5 pp), pero el Match Center sigue mostrando otro número: 20 de 25 selecciones a 24 h y 80 de 90 a 72 h pasan de 0,5 pp. Sin el interruptor, el tablero difiere de Intelligence en todas.

Lo que explica la diferencia, según los datos de esa corrida:

- El Match Center (`forecast-v1`) y Intelligence (`decision-v1`) calibran por caminos distintos y no usan el mismo momento de referencia. Las lecturas de Intelligence vienen de puntos de control entre T-36 h y T-90 min, con una edad mediana de 22 h y una máxima de 300 h (una lectura vieja de un partido lejano).
- Las diferencias más anchas de las últimas 24 h están repartidas entre 1X2, «más/menos de 2,5» y «ambos anotan», con un máximo de 4,1 pp; a 72 h llegan a 26,6 pp.
- Intelligence no tiene aún selecciones aprobadas, así que no hay nada que publicar desde allí por ahora.

**Decisión:** `FBI_PICKS_SOURCE` sigue apagado y no se publican picks experimentales. Para que el criterio se cumpla hace falta que el Match Center lea la misma probabilidad calibrada y el mismo punto de control (el último disponible antes del inicio) que Intelligence; es un cambio de contrato y de la web, y se hace detrás del interruptor y con esta misma herramienta como prueba de salida.

#### Por qué el Match Center no puede, por ahora, leer el número de Intelligence (9-nov-2026, 23:12 UTC)

La herramienta ya está desplegada (BE-021 entró en el despliegue de las 22:03 UTC) y la comparación oficial se repitió con ella: **sigue sin cumplirse.** A 24 h, con 119 selecciones de 25 partidos, el tablero con el interruptor y Intelligence coinciden en todas (0 de más de 0,5 pp), pero el Match Center difiere de Intelligence en 46 de 58 selecciones (mediana 2,2 pp, máximo 10,2 pp). A 72 h, 47 de 59 contra Intelligence y 101 de 114 contra el tablero con el interruptor (máximo 28,8 pp).

La salida obvia, que el Match Center muestre la probabilidad calibrada de Intelligence, tiene un obstáculo de calidad de datos que se midió con una lectura de solo lectura sobre los partidos de las próximas 72 h (y de las últimas 3 h):

| Mercado | Mercados con lectura de Intelligence | Resultados por mercado (promedio) | Suma de las probabilidades (mínimo–máximo) | Mercados en los que Intelligence no tiene todos los resultados |
| --- | --- | --- | --- | --- |
| 1X2 | 19 | 1,5 de 3 | 0,18–1,04 | 17 de 19 |
| Más/menos (OU) | 55 | 1,0 de 2 | 0,14–0,63 | 55 de 55 |
| Ambos anotan (BTTS) | 21 | 1,0 de 2 | 0,38–0,58 | 21 de 21 |

El pronóstico del Match Center (`forecast-v1`) cubre 70 mercados 1X2 y 62 de OU y de BTTS en la misma ventana, completos, con todos los resultados y sumando 1,0000. Intelligence solo guarda la probabilidad calibrada de lo que evaluó con un precio (una selección por mercado, casi siempre), así que no es una distribución: sustituir el número del Match Center por el suyo dejaría tablas incompletas que no suman 100 % y, además, descartaría el intervalo medido (que corresponde al número del modelo, no al calibrado de Intelligence).

**Lo que sí se puede hacer sin romper nada** (para decidir con el dueño, no se hizo):

1. Que Picks y Match Center no se contradigan donde coinciden: la tarjeta de un pick en el Match Center puede mostrar la misma probabilidad que la del tablero (la de la decisión), con su etiqueta, sin tocar el resto del mercado.
2. O al revés: que Intelligence calibre con el mismo modelo y el mismo momento (la probabilidad del Match Center al último punto de control) para todos los resultados de un mercado; es un cambio de la línea de modelos y tiene que pasar su propia puerta estadística.

Mientras tanto el criterio de «0 diferencias de más de 0,5 pp» solo es medible sobre las selecciones que ambos tienen, y hoy no se cumple. `FBI_PICKS_SOURCE` sigue apagado.
