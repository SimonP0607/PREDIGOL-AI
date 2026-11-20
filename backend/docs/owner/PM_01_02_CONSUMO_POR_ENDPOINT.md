# PM-01-02 · Consumo de API-Football por endpoint y carril, picos por minuto y tamaño de la base

*Plan Maestro PM, ola 1. Migración `0168` (BE-051, #402) y código (BE-051, segundo PR). Solo mide: no cambia ninguna petición, ninguna respuesta ni nada que
vea un lector. Coste: 0 peticiones y 0 USD.*

## Qué guarda

| Tabla | Qué es | Quién la escribe | Cuántas filas |
| --- | --- | --- | --- |
| `raw.provider_endpoint_usage` | Peticiones por día UTC, endpoint, carril y trabajo. Cuenta **cada intento** (los reintentos también), en el mismo punto donde se gasta `raw.provider_quota`; por eso la suma del día debe coincidir con ese libro | El cliente de API-Football: cuenta en memoria y suma en la tabla **como mucho una vez por minuto** por proceso y al cerrarse (una sentencia, no una escritura por petición) | Unas decenas al día |
| `raw.provider_minute_daily` | Resumen de cada día de `raw.provider_minute_usage` (que solo guarda 48 h): minutos con peticiones, total, minuto de máximo y percentiles 50/95/99 de peticiones por minuto (sobre los minutos que tuvieron alguna, como la medida del 19-nov: p95 85, máximo 202 de 450) | El limitador por minuto, en su poda de cada hora, antes de borrar lo que pasa de 48 h (ayer completo, hoy parcial) | Una al día |
| `audit.db_size_history` | Tamaño de la base en cada medida: `pg_database_size`, bytes por esquema y las 12 tablas más grandes | El informe de almacenamiento (`deploy/vps/bin/storage-report.sh`, 02:41, 08:41, 14:41 y 20:41 UTC) con el archivo `deploy/vps/db/db_size_history.sql`, como dueño | Cuatro al día |

El worker suma y nunca borra en las dos de `raw`; `audit.db_size_history` solo la escribe el dueño; la API lee las tres (la consola,
PM-04-05). Permisos en `deploy/vps/db/grants.sql` (bloque `$provider_usage$`).

## Carril y trabajo

* `job` es el `job_type` de la ejecución del libro (`raw.ingestion_runs`) que pidió: `RunLedger.open` lo deja en el contexto de la tarea.
  Una llamada sin ejecución (por ejemplo `/status` desde `capture_odds status`) cuenta como `sin_trabajo`.
* `lane` es **provisional** hasta PM-04-01: sale de la tabla de carriles del plan (`fbi.providers.quota.PROVISIONAL_LANES`: directo,
  cuotas, alineaciones, resultados, calendario, estadisticas_contexto, referencia, historicos, ampliacion, reparacion). Un trabajo que no
  está en la tabla cuenta como `sin_carril`.
* **Contrato para PM-04-01:** un trabajo que conoce su carril lo declara con `fbi.providers.quota.bind_usage_lane("<carril>")` (gana sobre
  la tabla); la tabla provisional puede sustituirse por la configuración de carriles. Como cada fila guarda también `job`, la historia se
  puede releer con los carriles nuevos sin volver a pedir nada al proveedor. Un carril es `[a-z0-9_]`, 40 caracteres como mucho.

## Interruptores

| Nombre | Dónde | Por omisión | Qué hace |
| --- | --- | --- | --- |
| `FBI_PROVIDER_USAGE` | `/etc/predigol/app.env` (plantilla `deploy/vps/app.env.example`) | **encendido** (sin la línea) | `0`/`off`/`false`/`no`: el cliente no cuenta y el limitador no guarda el resumen diario. El worker lo lee al arrancar: tras cambiarlo hay que reiniciar el worker |
| `PREDIGOL_DB_SIZE_HISTORY` | `/etc/predigol/predigol.env` | encendido (sin la línea) | `0`: el informe de almacenamiento no escribe `audit.db_size_history` (el resto del informe sigue igual) |

**Por qué nacen encendidos** (desviación anotada de «todo nace apagado»): solo miden, no cambian nada visible ni predictivo, y la ficha
pide siete días de medida **antes** de PM-04-01 (que mide su «antes y después» con estas tablas). Un fallo al escribir se anota en el
registro (`quota.endpoint_usage_not_kept`, `quota.minute_summary_not_kept`, «not kept in audit.db_size_history») y **nunca** cuesta la
petición ni para el informe. Memoria: un diccionario de unas decenas de claves por proceso (tope 5.000; lo que no cabe se cuenta como
descartado).

## Cómo se lee (solo lectura)

```sql
SET default_transaction_read_only = on; SET statement_timeout = '90s';
-- consumo de ayer por carril y endpoint
SELECT lane, endpoint, sum(requests) FROM raw.provider_endpoint_usage
 WHERE usage_date = current_date - 1 GROUP BY 1, 2 ORDER BY 3 DESC;
-- criterio de aceptación: diferencia con el libro diario < 1 %
SELECT q.quota_date, q.spent, u.total, round(100.0 * (q.spent - u.total) / nullif(q.spent, 0), 2) AS diferencia_pct
  FROM raw.provider_quota q
  JOIN (SELECT usage_date, sum(requests) AS total FROM raw.provider_endpoint_usage WHERE provider = 'api_football' GROUP BY 1) u
    ON u.usage_date = q.quota_date
 WHERE q.provider = 'api_football' ORDER BY 1 DESC LIMIT 14;
-- picos por minuto de cada día
SELECT usage_date, minutes_active, requests, max_per_minute, p95, complete FROM raw.provider_minute_daily ORDER BY 1 DESC LIMIT 14;
-- crecimiento de la base
SELECT measured_at, pg_size_pretty(db_bytes) FROM audit.db_size_history ORDER BY 1 DESC LIMIT 12;
```

Diferencias esperables con el libro: el día del despliegue (el contador empieza a mitad de día), y lo que un proceso matado no llegó a
volcar (como mucho un minuto de sus peticiones). El libro diario se siembra con `raw.ingestion_runs` al crear la fila del día; el contador
no, así que el primer día tras el despliegue no cuenta para el criterio.

## Vuelta atrás

`FBI_PROVIDER_USAGE=off` (copia fechada de `app.env` y reinicio del worker) o `PREDIGOL_DB_SIZE_HISTORY=0`, sin despliegue; o `revert` del
segundo PR de BE-051. Las tablas se quedan sin escritor y **no se borran**: el downgrade de la migración `0168` se niega mientras tengan medidas.
