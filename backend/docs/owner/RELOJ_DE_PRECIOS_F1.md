# Reloj de precios (Plan Maestro, fase F1)

**Qué es.** Una serie nueva y ordenada de *todas* las cuotas que la API de proveedor devolvió antes del partido, cada una con su
minuto exacto (`captured_at`) y los minutos que faltaban para el inicio (`minutes_to_ko`). Se construye **solo** a partir de los
cuerpos crudos de `/odds` que ya se guardan en RAW (`/srv/predigol/raw`), sin pedirle nada nuevo al proveedor. Sirve de base para
el CLV real, el movimiento de línea, la liquidación de mercados nuevos y los modelos futuros. **No cambia ningún pick, ninguna
probabilidad ni el modo SHADOW.**

## Qué escribe (y qué no)

Migración **0077**, solo aditiva (cuatro tablas nuevas, nada existente se altera):

| Tabla | Para qué |
|---|---|
| `market.market_families` | Vocabulario pequeño de familias (resultado, goles, goles por mitad, córners, tarjetas, tiros, …). |
| `market.market_definitions` | Un registro por tipo de apuesta del proveedor (338): familia, periodo, sujeto, cómo se lee su `value`, si se extrae y su estado. Es lo que decide qué hace el extractor. |
| `market.odds_extractions` | El libro de control: un registro por cuerpo RAW distinto, con su estado (`ok`, `empty`, `no_fixture`, `after_kickoff`, `error`), la versión del extractor y cuántas cuotas se escribieron o se rechazaron. |
| `market.odds_quotes` | Las cuotas, particionadas por mes. Llave: partido, casa, mercado, selección, línea, `captured_at`. Una cuota nunca se sobrescribe: la sigue la siguiente. |

Hoy se estructuran **55 mercados** de las familias resultado, goles, goles por mitad, córners, tarjetas y tiros de equipo
(taxonomía `tax-v2`; la `tax-v1` tenía 53 y `tax-v2` añade los dos hándicaps asiáticos por mitad, ver más abajo). Los demás (jugadores, tiempos, especiales, otros deportes…) **siguen intactos en RAW**: activarlos después es
cambiar un registro de `market_definitions` y volver a leer; no se pierde nada por no extraerlos hoy.

## Reglas que se respetan

* **Sin datos posteriores al inicio.** Se escribe con la hora en que *nosotros* vimos el cuerpo (`fetched_at`) si fue antes del
  inicio; si se pidió después (el proveedor guarda cuotas pre-partido durante 7 días), solo vale su propia marca `update` y solo si
  es anterior al inicio; si no, **no se escribe nada**. `minutes_to_ko` se mide contra el inicio que traía el propio cuerpo.
* **Una cuota es la primera vez que se vio ese cuerpo**, no cada consulta: RAW guarda los cuerpos idénticos una sola vez. Las
  consultas siguen en `market.odds_asks`.
* **Se lee con las mismas funciones del pipeline** para los cinco mercados que ya usa (`1X2`, `OU`, `BTTS`, `DC`, `AH`): ambas
  series no pueden discrepar sobre una selección (hay una prueba precio por precio contra `iter_odds`).
* **Rechazar antes que adivinar.** Una selección fuera de su vocabulario, una línea imposible (p. ej. 2.3 goles) o una cuota que no
  es cuota (1.00, 0, ≥ 1000) se rechaza y se cuenta; nunca se corrige en silencio.
* **Handicap asiático:** el proveedor repite el hándicap del local en las dos filas; la fila del visitante se niega. Está medido
  con datos reales del servidor en tres mercados: el 4 (partido completo), el **19** (1.ª parte) y el **104** (2.ª parte). En los
  tres el par suma 1,085–1,094 (mediana) leído así y entre 0,28 y 1,9 leído al revés, y el precio del visitante *sube* con el
  número impreso (nunca baja). Un pariente solo se extrae cuando se ha medido lo mismo sobre sus propios precios.
* **Reintentos sin esconder errores.** Los cuerpos ilegibles o sin partido se anotan en el libro y se reintentan cada 2 h durante
  14 días; lo que falla se ve en el panel (Admin → PrediGol Intelligence → Mercados → Reloj de precios).
* **Una versión nueva del extractor reemplaza lo derivado de un cuerpo** (borra y reescribe sus cuotas); RAW no se toca nunca.

## Cómo corre

* **Worker:** trabajo `odds_quotes_extract` cada 10 minutos, hasta 300 cuerpos por vuelta y 240 s. Se apaga con
  `FBI_QUOTES_EXTRACT=0`. Candado `fbi.odds_quotes_extract` (una sola instancia). El perro guardián lo da por colgado a los 20 min.
* **Frenos propios:** no escribe si el disco libre baja de 8 GB ni si `market.odds_quotes` pasa de 25 GB; en ese caso el trabajo
  se queda quieto y lo dice en su registro. Nada se borra solo.
* **Relleno histórico (a mano, desde `backend/`):**

```bash
python -m scripts.extract_odds_quotes status                      # qué hay estructurado y qué falta
python -m scripts.extract_odds_quotes sample --n 300              # ensayo en seco sobre los últimos cuerpos, no escribe nada
python -m scripts.extract_odds_quotes run --since 2026-09-25 --limit 20000 --batch 500 --max-seconds 3000
```

  `run` solo escribe las tres tablas de arriba, se puede repetir y no vuelve a leer lo ya hecho por la misma versión.

## Cómo medir el almacenamiento (semana 1)

1. `status` da filas, partidos, GB de la tabla y cuerpos pendientes.
2. Tras un lote conocido (`run --limit 2000`): filas por cuerpo = `quotes_written / payloads` del libro; bytes por fila =
   `pg_total_relation_size('market.odds_quotes') / filas`.
3. Proyección mensual = cuerpos RAW por mes × filas por cuerpo × bytes por fila. Estimación previa: ~1.500 cuotas por cuerpo y
   ~100–150 B por fila con índices. **Se confirma con datos reales antes de rellenar todo el histórico.**
4. Si la tabla se acerca al freno, la salida es compactar (borrar cuotas consecutivas idénticas por llave) con respaldo verificado
   previo; RAW permite regenerarlo todo. La función de compactación se escribe solo si la medición lo exige.

## Límite conocido

Como RAW guarda los cuerpos idénticos una sola vez, una secuencia A → B → A de precios entre dos consultas solo deja constancia de
A y B; la vuelta a A se recupera con `market.odds_asks` (cada consulta apunta a su cuerpo por `payload_hash`).

Desde BE-004 (F4a del plan de Partidos y Match Center) esa lectura existe: `fbi.odds.quote_current` toma la última consulta
anterior al inicio, su cuerpo por `payload_hash` y solo las cuotas de ese cuerpo (`extraction_id`), y es lo que sirve
`GET /api/v1/matches/{id}/markets/catalog`. Tras A → B → A la cuota vigente es A y su antigüedad cuenta desde la consulta que la
devolvió. Dos límites: `odds_asks` guarda solo el hash de la **primera página** de cada respuesta (con `fixture=` la respuesta es
una sola página: el proveedor pagina por partidos, diez por página), y una página posterior solo cuenta si se descargó por
primera vez en esa misma consulta; si no, se deja fuera y la respuesta dice `partial` (falta una página, nunca una cuota vieja).
Si algún día se compacta la tabla (borrar cuotas consecutivas idénticas), esta lectura debe cambiar a la vez: hoy da por hecho
que cada cuerpo conserva todas sus cuotas.

## Cómo deshacerlo

* Parar solo la lectura: `FBI_QUOTES_EXTRACT=0` y reiniciar el worker.
* Quitar todo: `alembic downgrade 0076` (borra las cuatro tablas nuevas; RAW y todo lo demás quedan intactos). Hacer antes el
  respaldo habitual de despliegue.

## Medición real en el servidor (22 oct 2026, solo lectura)

Estado del reloj a las 17:11 UTC; el trabajo empezó a leer a las 13:15 UTC y lleva 6.445 cuerpos en 4 h:

| Dato | Valor |
|---|---|
| Cuerpos `/odds` en RAW desde el 25 sep | 12.249 (≈ 454 al día) |
| Leídos con éxito | 6.222 → 6.053.873 cuotas en 1.437 partidos |
| Filas por cuerpo | ≈ 973 (la estimación previa de 1.500 era alta) |
| Peso de la tabla | 1,073 GB para 6,05 M filas → **≈ 177 B por fila** (con índices) |
| Proyección mensual | ≈ 13.600 cuerpos × 973 × 177 B ≈ **2,35 GB al mes** (≈ 2,6 GB con `tax-v2`); el freno está en 25 GB, o sea ≈ 10 meses |
| Pendientes | 5.916 (incluye 112 sin partido que se reintentan); el trabajo vacía entre 1.500 y 1.800 por hora (los 300 de cada vuelta), empezando por los cuerpos nunca leídos y los más antiguos; quedará en unas 3,5 h |
| `after_kickoff` | 111 cuerpos, 0 cuotas (por diseño: se pidieron tras el inicio y su marca `update` no es anterior) |
| Cuotas rechazadas | todas son precio `1.00` (líneas muertas del proveedor); ninguna otra causa |

Conclusiones: el almacenamiento cabe con holgura y **no hace falta compactar todavía**; el relleno histórico es el propio trabajo
de cada 10 minutos (no hay que lanzar `run` a mano); y `tax-v2` hace que el extractor relea (borrar y reescribir) los cuerpos
leídos con `tax-v1` en segundo plano, a 300 cuerpos cada 10 minutos, cuando se despliegue.

**Hándicaps pendientes.** Con el mismo método (400 cuerpos más nuevos, dos medidas independientes: patrón de las etiquetas y
pendiente del precio del visitante) los mercados 56, 81, 125, 126 y 152 siguen la misma convención. Siguen aparcados a propósito:
son córners y tarjetas, y su lectura y liquidación se decide por familia en la fase F9.
