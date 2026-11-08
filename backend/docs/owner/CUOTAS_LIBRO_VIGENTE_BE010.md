# Libro vigente de cuotas (BE-010, plan Cuotas, ola 1)

**Qué es.** Una tabla nueva, `market.book_current` (migración **0128**, solo aditiva), con el precio **vigente** de cada partido
próximo para cada tipo de apuesta que llega del proveedor y que la taxonomía nueva sabe leer (`tax-v3`): una fila por partido y
tipo, con las cuotas de cada casa, la mejor cuota y su casa, cuántas casas cotizan y, solo donde tiene sentido, la cuota justa,
la diferencia con ella y la marca de «atípica». Es la base del explorador de Cuotas (olas siguientes); **hoy nadie la lee**.

- **No toca nada de lo que usan modelos, picks, SHADOW ni el parlay**: `odds_snapshots`, `market_consensus` y `odds_quotes` se
  escriben igual que antes (los 55 tipos de `tax-v2` y su extractor no cambian) y la huella de modelos es la misma.
- **No pide nada al proveedor**: lee la base y los cuerpos que ya están en RAW.
- **Es una caché**: se reconstruye entera desde RAW cuando se quiera. Las filas de partidos que empezaron hace más de **6 h** se
  borran solas; su historia sigue en RAW y, para los tipos que ya se extraen, en `odds_quotes`.

## Qué respuesta manda y qué se enseña

- **La respuesta vigente** es la que dice `quote_current` (la misma función que usa el Match Center): la última consulta antes del
  inicio. Tras A → B → A vale A. Una respuesta **vacía** retira todos los precios: las filas del partido se borran. Si la consulta
  más nueva trae un cuerpo que el extractor aún no ha leído, queda el anterior y la fila lo dice (`newer_pending`).
- Cada fila guarda la huella del cuerpo (`payload_hash`), cuándo se vio por primera vez (`captured_at`), la hora del proveedor
  (`provider_update_at`), la consulta que lo confirmó (`checked_at`) y desde cuándo manda (`in_force_since`).
- **Nunca se enseña mal**: si un solo valor de un tipo no se puede leer, ese tipo no se guarda para ese partido; tampoco si el
  proveedor le cambia el nombre o si una casa se contradice. Se cuenta y queda en el registro del trabajo.
- **Cuota justa** solo si el tipo cubre todos los resultados, tiene método (Shin, o proporcional en los «número exacto» y rangos)
  y cotizan **3 casas o más** con el libro completo de esa línea. Hándicap asiático: Local h con Visitante −h (corrige E1). La
  diferencia es `mejor × p − 1`; por encima de **+25 %** la selección sale marcada como atípica (sospechosa, no una ganga).
- **Mejor cuota**: la más alta de todas las casas vigentes (una sola definición, E12).
- Las casas van por el id del proveedor (`market.bookmakers.provider_bookmaker_id`).

## Los 137 tipos (`tax-v3`)

Se validó cada lector contra cuatro respuestas reales (Premier League con jugadores, Serie A, Primera A de Colombia, Copa del Rey):
11.724 valores de 127 tipos leídos sin un fallo, y los 42 tipos que ya se extraen se leen igual que el extractor, valor por valor.
**127 tipos se muestran** (más el 307, gemelo del 339). **10 quedan ocultos**, con su motivo en el código:

| Tipo | Por qué no se muestra |
|---|---|
| 78 «RTG_H1» | Nombre opaco (parece resultado y goles de la 1.ª parte: «Empate/Menos de 1,5» vale lo mismo que el 0:0 al descanso) |
| 215 «Player Singles» | Clasificado en otros deportes; precio a precio es la suma de «tiros de jugador» local y visitante (240 y 241) |
| 213 «Player Triples» | Clasificado en otros deportes; no coincide con ningún mercado de las muestras |
| 275 «Away Player Shots On Target Total» | Sus valores son, precio a precio, los goles de cabeza (228 y 245): nombre y valores no cuadran |
| 276 «Away Player Shots Total» | Dice jugador pero trae un más/menos de equipo sin ningún jugador |
| 299 «Cards over/under between 0 and 10 m» | «Más» y «Menos» sin línea |
| 61, 224, 225, 298 | Llegan en eliminatorias, pero no hay ninguna muestra: su lector no está validado |

Un tipo nuevo que no esté en `tax-v3` tampoco se muestra: se cuenta como `unknown_bets`.

## El interruptor

`FBI_ODDS_BOOK` en `/etc/predigol/app.env` (plantilla en `deploy/vps/app.env.example`). **Apagado por defecto**: cualquier valor
que no sea `1`, `on`, `true` o `yes` es apagado. Para encenderlo: `FBI_ODDS_BOOK=1` y reiniciar el worker. Encendido, el trabajo
`odds_book_build` corre cada 10 min (`FBI_ODDS_BOOK_MINUTES`), reconstruye los partidos cuyas consultas o extracciones cambiaron
desde su última vuelta, borra las filas de partidos empezados hace más de 6 h y deja su vuelta en `raw.ingestion_runs`. Una vuelta
sin nada que hacer no deja registro. Depende del extractor (`odds_quotes_extract`, encendido por defecto).

## Reconstruir a mano

Desde `backend/` (en el servidor, dentro del worker). En seco por defecto: lee y cuenta, **no escribe nada**:

```
docker exec -w /app predigol-worker python -m scripts.rebuild_odds_book                  # todo lo que debe tener el libro
docker exec -w /app predigol-worker python -m scripts.rebuild_odds_book --fixture 9207   # un partido
docker exec -w /app predigol-worker python -m scripts.rebuild_odds_book --since 2026-11-08
docker exec -w /app predigol-worker python -m scripts.rebuild_odds_book --apply          # escribirlo (y purgar lo viejo)
```

Imprime los partidos por estado, las filas que se insertarían, cambiarían, se quedarían igual o se borrarían, los tipos ocultos
y por qué, los bytes del resumen por partido y el tamaño de la tabla. Repetirlo no cambia nada (ni `built_at`). Funciona con el
interruptor apagado (el interruptor es del worker). Un `--since` de más de 6 h atrás escribe filas que la siguiente vuelta del
worker vuelve a borrar.

**Tamaño medido** con las cuatro respuestas reales completas (8-nov): 393 filas y 9.867 precios ocupan 540 KB con índices y TOAST
(unos 135 KB por partido, 55 B por precio). Para los 536 partidos de la auditoría, entre **70 y 100 MB** (lo primero escalando por
partido, lo segundo por sus 1,99 millones de precios, de los que un 8 % es de tipos ocultos), dentro de lo previsto (50–150 MB).
Se confirma con la primera reconstrucción en el ensayo antes de producción. Un partido grande tarda unos 50–80 ms.

## Comprobarlo sin tocar nada

Con `predigolctl psql` (sesión de solo lectura):

```sql
SELECT count(*) AS filas, count(DISTINCT fixture_id) AS partidos, max(built_at) AS ultima,
       pg_size_pretty(pg_total_relation_size('market.book_current')) AS tamano
  FROM market.book_current;
SELECT started_at, status, rows_written, left(notes, 300) FROM raw.ingestion_runs
 WHERE job_type = 'odds_book_build' ORDER BY started_at DESC LIMIT 5;
```

El seco (`rebuild_odds_book` sin `--apply`) dice además qué cambiaría si se reconstruyera ahora. Y la huella de modelos debe seguir
igual: `python3 scripts/model_code_guard.py fingerprint dir=.`.

## Vuelta atrás

1. Apagar: quitar `FBI_ODDS_BOOK` (o `FBI_ODDS_BOOK=0`) y reiniciar el worker. Las filas que queden no las lee nadie y la purga ya
   no corre; se pueden dejar.
2. Vaciar: `TRUNCATE market.book_current;` con el rol dueño (es una caché; se reconstruye con `--apply`).
3. Quitar la tabla: `alembic downgrade 0127`, con el respaldo habitual de despliegue. RAW y todo lo demás quedan intactos.
