# Auditoría de continuidad de datos: portátil → servidor (9 oct 2026)

**Veredicto: no se perdió ningún dato en el traslado.** Las 138 tablas del portátil están completas en el servidor
(51.752.042 filas, ninguna menos) y los 80.352 ficheros RAW anteriores al corte existen en disco. Ninguna ventana de
captura de cuotas cayó dentro de los huecos, y no había partidos en juego mientras el worker estuvo parado.

Medido el 9 oct entre las 15:45 y las 16:30 UTC. La base del portátil quedó congelada en el corte y se comparó tabla a
tabla con la del servidor. Antes de mirar nada se tomó una copia completa (`predigol-20261009T154508Z-fase0-continuidad`),
y su prueba de restauración pasó en 408 s.

## 1. Línea temporal (UTC; Bogotá = UTC − 5)

| Hora UTC | Qué pasó | Fuente |
|---|---|---|
| 03:22:27 | Último trabajo normal del portátil (monitor de investigación) | `raw.ingestion_runs` |
| 03:24:45 | **El worker del portátil muere**: Windows cerró la distro de WSL a mitad de una pasada de picks | run `pick_pipeline` interrumpido |
| 03:41:24 | El worker del portátil vuelve (código 96e2c44); captura de recuperación: 1 petición, 313 cuotas | heartbeat `Mila:worker` |
| 03:44:29 | **Última escritura válida del portátil** (fin de la última pasada de picks) | `raw.ingestion_runs` |
| 03:44:50 | El worker del portátil se detiene limpio y queda marcado para no volver a arrancar | `stopped_at` del heartbeat |
| 03:48:23 | Copia final del portátil: volcado de 654,6 MB en 63 s y RAW de 863 MB | registro del corte |
| 03:50–03:54 | Copia al servidor con sha256 comprobados | registro del corte |
| 03:54–03:59 | Importación: 138 tablas con el mismo número de filas que el manifiesto | registro del corte |
| 03:59 | PostgreSQL, API, web y Caddy sanos en el servidor | registro del corte |
| **04:02:39** | **Primer dato del servidor**: captura de cuotas, 9 peticiones, 2.895 cuotas | `raw.ingestion_runs` |
| 04:02:49 | Primera pasada de picks del servidor | idem |
| 04:06:38 | Primera reparación de resultados y primer detalle post-partido | idem |
| 04:07:47 | Primera sincronización de resultados y de partidos | idem |
| 04:09:38 | Primer cierre prepartido del proveedor | idem |
| 04:18 | Prueba de reinicio real del servidor (todo volvió en 36 s) | registro del corte |
| 04:24:19 | Primer refresco de contexto (lesiones, alineaciones) | idem |
| **04:58:39** | **Primer seguimiento en vivo**: Daejeon Citizen – Jeonbuk, K League 1, saque 05:00 | idem |
| 05:00:04 | Primera captura de cuotas en vivo | idem |
| 05:05:00 | La IA abre el día 9 oct (00:05 Bogotá) | `ai.day_plans` |

## 2. Huecos (worker sin correr)

| Hueco | Desde | Hasta | Duración | Causa |
|---|---|---|---:|---|
| G1 | 03:24:45 | 03:41:24 | 16 min 39 s | Windows cerró la distro de WSL del portátil |
| G2 | 03:44:50 | 04:02:39 | 17 min 49 s | El corte portátil → servidor |
| Servidor | 04:17 a 14:42, 12 veces | — | de 1 s a 2 min 44 s cada uno | Reinicios: prueba de reinicio, despliegues y dos reinicios del monitor (11:48 y 13:00) |

**Qué había que hacer durante G1 y G2, y qué pasó con ello:**

- **En vivo:** nada. La última captura en vivo del portátil fue a las 03:03 y el primer partido siguiente empezó a
  las 05:00. No se perdió ninguna cuota ni ningún estado en vivo.
- **Ventanas de captura prepartido** (T-72h, 48h, 24h, 12h, 6h y 3h, bandas de 45 min): 547 partidos seguidos con
  saque desde el 9 oct; 517 ventanas se cerraron desde las 00:00 UTC del 9 oct. 500 tienen captura, **ninguna de las 17
  sin captura cayó en un hueco**: en todas hubo capturas durante la banda. Detalle en §5.
- **Resultados y detalle post-partido:** los 32 partidos seguidos terminados desde el 8 oct tienen resultado y los
  cuatro conjuntos de detalle (eventos, alineaciones, estadísticas de equipo y de jugador).
- **Cierre prepartido del proveedor** (lo guarda 7 días): 25 con precio, 5 sin cuotas en el proveedor, 2 pedidos
  después del inicio. El único partido que empezó cerca de los huecos (Daejeon – Jeonbuk) tiene su cierre.
- **Pasadas de picks:** dos interrumpidas (03:24 y las de los reinicios del servidor). No se pierde nada: cada pasada
  vuelve a evaluar todos los instantes de captura.
- **IA:** ninguna pasada vencía en los huecos; el día 9 se abrió a las 05:05. Hoy: 81 primeras pasadas, 70 previas, 26
  finales; ningún partido empezó sin su pasada final.

## 3. Comparación tabla a tabla

Método: para cada tabla con `id` entero, todas las filas del servidor con `id` ≤ el máximo del portátil deben seguir
ahí; para las demás, el servidor debe tener al menos las filas del portátil.

| Resultado | Tablas |
|---|---:|
| Idénticas en lo anterior al corte | 96 |
| Crecieron (sin `id`; nada faltó) | 42 |
| Con filas de menos | **0** |
| Ausentes | **0** |
| **Filas del portátil / encontradas en el servidor** | **51.752.042 / 51.752.042** |

Las tablas que pidió el dueño (portátil congelado → servidor ahora):

| Dato | Portátil | Servidor |
|---|---:|---:|
| Partidos (`core.fixtures`) | 245.872 | 245.872 |
| Resultados | 228.904 | 228.919 |
| Cuotas prepartido (instantáneas) | 627.704 | 807.388 |
| Consenso de mercado | 485.913 | 615.675 |
| Alineaciones (partido / jugador) | 436.704 / 8.418.096 | 436.746 / 8.418.955 |
| Bajas (`player_absences`) | 185.137 | 185.185 |
| Clasificaciones | 24.905 | 25.618 |
| Estadísticas de equipo / de jugador | 350.844 / 5.241.817 | 350.890 / 5.242.608 |
| Eventos | 3.193.233 | 3.193.524 |
| Jugadores / equipos / entrenadores | 193.513 / 8.244 / 13.453 | 193.517 / 8.244 / 13.454 |
| Traspasos | 1.079.281 | 1.079.281 |
| Pronósticos de los modelos | 1.230.498 | 1.439.645 |
| Picks / candidatos | 19.715 / 121.539 | 31.352 / 203.580 |
| Paquetes / revisiones de la IA | 887 / 421 | 2.789 / 3.340 |
| Post-mortems (de pick / de partido) | 34 / 0 | 42 / 7 |
| Payloads RAW (filas) | 80.352 | 84.466 |
| Ficheros RAW en disco sin su fila / filas sin fichero | — | 0 / **0** |
| Ejecuciones registradas | 18.196 | 20.257 |

## 4. Clasificación

| Clase | Qué |
|---|---|
| **CORRECTO** | Las 138 tablas y los 84.466 ficheros RAW. |
| **RECUPERABLE** | Nada pendiente: detalle post-partido completo, cierres prepartido pedidos, las pasadas interrumpidas se rehicieron solas. |
| **IRRECUPERABLE** | Nada por los huecos (no había partidos en juego; ninguna ventana venció dentro). |
| **DUPLICADO** | Versiones de modelo 258–260 (13:31–13:47 UTC, error del arreglo de rendimiento): 89.585 pronósticos, 3.275 candidatos, 493 picks en sombra. Separadas por versión, sin borrar; decisión del dueño. |
| **INCONSISTENTE** | (a) El corte abrió versiones de modelo nuevas (252–254) con el mismo código: un archivo con finales CRLF en el portátil; corregido en `bb5dbda`. (b) El ciclo de IA 87 quedó "en curso" tras el reinicio de las 13:00; corregido en `af4d36a`. (c) Las 17 ventanas de §5. |

## 5. Las 17 ventanas sin captura (ninguna por el corte)

| Liga (temporada) | Partidos | Ventanas | Por qué |
|---|---:|---:|---|
| Thai League 1 (2026) | 8 | 11 | La cobertura del proveedor marcaba la temporada sin cuotas y `/odds/mapping` no listaba sus partidos: la captura no la pide, por diseño (una respuesta vacía gasta una petición). El refresco diario del catálogo (14:05:11) trajo la cobertura nueva con cuotas, y desde las 14:06 se piden. Uno (21569, saque 9 oct 11:00) terminó sin ninguna cuota. |
| Indian Super League (2026) | 2 | 2 | Igual: cobertura actualizada a las 14:05:11; primera petición a las 14:07; el proveedor aún no devuelve cuotas. |
| Copa del Rey (2026) | 2 | 2 | El proveedor marca la temporada sin cuotas: no se pide, por diseño. |
| Liga MX y Primera División (2026) | 3 | 3 | En el portátil, antes del corte (bandas entre las 23:30 del 8 oct y las 02:00 del 9 oct). |

## 6. Reinicios del servidor el 9 oct

Detectados por las ejecuciones que el worker siguiente encontró interrumpidas: 04:17, 07:03, 10:27, 12:34, 12:58,
13:17, 13:28 y 14:07. Más los que no interrumpieron nada (11:48 del monitor, despliegues de 13:47, 14:25 y 14:41).
Ninguno duró más de 2 min 44 s. Lo único que cada uno pierde es lo efímero (cuotas en vivo de esos segundos) y la
pasada de picks en curso, que se rehace. Desde el arreglo `2674974` el latido ya no depende del pipeline, y el
monitor no ha vuelto a reiniciar el worker.
