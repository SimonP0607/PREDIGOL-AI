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

Hoy se estructuran **53 mercados** de las familias resultado, goles, goles por mitad, córners, tarjetas y tiros de equipo
(taxonomía `tax-v1`). Los demás (jugadores, tiempos, especiales, otros deportes…) **siguen intactos en RAW**: activarlos después es
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
* **Handicap asiático:** el proveedor repite el hándicap del local en las dos filas; la fila del visitante se niega (medido en el
  mercado 4). Los parientes del 4 (19 y 104) **no se extraen aún**: su signo está sin confirmar con datos del servidor.
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

## Cómo deshacerlo

* Parar solo la lectura: `FBI_QUOTES_EXTRACT=0` y reiniciar el worker.
* Quitar todo: `alembic downgrade 0076` (borra las cuatro tablas nuevas; RAW y todo lo demás quedan intactos). Hacer antes el
  respaldo habitual de despliegue.

## Pendiente de F1

Medición real en el servidor (solo lectura): nombres de apuesta, vocabularios de valores, signo de los hándicaps 19 y 104,
filas por cuerpo y bytes por fila; después, plan de relleno desde 2026-09-25 con el almacenamiento medido.
