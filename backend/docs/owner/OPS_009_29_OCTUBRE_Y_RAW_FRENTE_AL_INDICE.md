# OPS-009 · El 29-oct-2026 y los archivos RAW frente al índice

Fecha: 20 nov 2026. Tarea PM-01-03 del Plan Maestro PM (ola 1). Solo lectura: no cambia código, datos, archivos ni configuración. Coste:
0 peticiones y 0 USD.

Las dos preguntas que dejó abiertas la medición del 19-nov-2026 (nota 02 del plan, apartado 8):

1. ¿Por qué el libro diario de cuota (`raw.provider_quota`) marcó **60.000** el 29-oct si los trabajos solo registraron **12.819** llamadas?
2. ¿Por qué hay **619.351** archivos en el RAW y solo **330.337** filas en su índice (`raw.ingestion_payloads`)?

**Las dos causas quedan determinadas**, con las cifras reproducidas por las consultas del final.

## 1. El 29-oct-2026

### Qué pasó

| Hora UTC (29-oct) | Hecho | Evidencia |
| --- | --- | --- |
| 00:00–04:44 | Día normal: 495 respuestas guardadas en el RAW | `raw.ingestion_payloads` del día: todas entre las 00 y las 04 h |
| **04:45** | El proveedor empieza a contestar **como plan gratuito**: «You have reached the request limit for the day» y «Free plans do not have access to the Ids parameter / to this season / to this date» | Primer `last_error` con esos textos en `raw.ingestion_runs` |
| 04:45–21:31 | Cada petición sale, gasta una unidad de **nuestro** presupuesto y vuelve con error. 3.715 ejecuciones fallan con esos textos; ninguna guarda respuestas | `last_error`; `payloads_stored = 0` en todas las ejecuciones desde las 04:45 |
| **21:32:07** | Nuestro presupuesto diario llega a **60.000** (`FBI_APIFOOTBALL_DAILY_BUDGET`) | `raw.provider_quota.updated_at` del 29-oct |
| 21:32:25–23:59 | Nuestro presupuesto rechaza todo («daily budget of N requests exhausted»): ya no sale ninguna petición | Primer error de presupuesto agotado a las 21:32:25 |
| 30-oct | Día normal (14.671 peticiones, ningún error de plan gratuito ni de límite del día) | `raw.provider_quota`; `last_error` del 30-oct |

En el 26-oct, 27-oct, 28-oct, 30-oct, 31-oct y 1-nov no hay **ni un** error de «request limit» ni de «Free plans». Solo el 29-oct.

**Causa:** la suscripción de pago (prepago, sin renovación automática) dejó de estar activa a las 04:45 UTC y la cuenta pasó al plan
gratuito (100 peticiones al día, sin el parámetro `ids` ni temporadas o fechas fuera de su ventana). La fecha de fin actual,
**29-nov-2026 21:45:57 UTC**, es compatible con una renovación hecha el 29-oct hacia las 21:45 UTC (un mes justo), cuando nuestro
presupuesto ya estaba agotado; por eso la ingesta no volvió hasta medianoche. Esto último es una inferencia: lo confirma el historial
de pagos del panel del proveedor, que no se ha consultado. PM-01-01 (OPS-008) ya avisa con 10 días de margen de este mismo vencimiento.

### Por qué el libro dice 60.000 y los trabajos 12.819

Los dos cuentan cosas distintas:

* `raw.provider_quota.spent` suma **cada intento que sale**, antes de enviarlo (`fbi.providers.quota`, «it counts every request ISSUED -
  refused ones included»). Lo gasta el cliente en `ApiFootballClient.get` antes de cada intento.
* `raw.ingestion_runs.api_calls` lo escribe cada trabajo al cerrar, y varios cuentan **solo las respuestas buenas** (`len(raws)`): la
  captura de cuotas previas (`odds_capture`) y la de cuotas en vivo (`live_odds_capture`), entre otros. Un intento que vuelve con
  error no llega a `api_calls`; sí a `errors`.

La resta del 29-oct es **60.000 − 12.819 = 47.181** peticiones sin trabajo que las reclame (un día normal: entre −144 y 419, menos del
3 %). Esas 47.181 son los intentos fallidos de los trabajos que no los cuentan en `api_calls`:

| Trabajo y estado (29-oct) | Ejecuciones | `api_calls` | `errors` |
| --- | --- | --- | --- |
| `odds_capture` fallidas | 201 | 0 | **45.328** |
| `live_odds_capture` fallidas | 1.738 | 0 | **1.738** |
| `odds_capture` abortadas | 30 | 0 | **157** |
| `context_due` abortadas | 5 | 0 | **5** |
| **Suma** | | | **47.228** |

Son **47.228** intentos fallidos sin `api_calls` frente a **47.181** peticiones sin reclamar: una diferencia de 47 (0,1 %), del
orden de lo que cualquier día queda sin reclamar, y en parte errores que no fueron peticiones (desde las 21:32 las negativas de nuestro
propio presupuesto también se anotan como error). El resto de trabajos fallidos (por ejemplo `reference_refresh`, 5.303 llamadas y
5.303 errores) sí cuenta sus intentos en `api_calls` y está dentro de las 12.819.

Las 3.726 ejecuciones fallidas del día suman 56.803 errores; con 1.154 completadas y 36 abortadas son las 4.916 ejecuciones del 29-oct.
La captura de cuotas previas se lleva casi todo: cada una de sus 201 ejecuciones fallidas siguió partido tras partido, unas 225 peticiones
fallidas de media, porque un error dentro de una respuesta 200 no la detiene.

### Por qué no se paró antes (hallazgo, sin cambio)

`ApiFootballClient.get` marca el éxito en el cortacircuitos (`record_success`) **antes** de leer el objeto `errors` de una respuesta
HTTP 200; un «request limit for the day» o «Free plans …» se convierte en `ProviderError`, que no abre el cortacircuitos ni se reintenta,
y el trabajo pasa a la siguiente petición. Así se gastaron 47.000 unidades del presupuesto propio en 16 horas sin traer nada.

Este PR **no lo cambia** (PM-01-03 es de lectura y la regla de la ola es no tocar el comportamiento del presupuesto ni de la ingesta).
Propuesta para el coordinador, como tarea aparte: tratar «request limit for the day» y «Free plans …» como fallo del cortacircuitos (o
parar el trabajo en el primero), con su interruptor y su prueba. Mientras tanto:

* OPS-008 avisa del vencimiento con 10 días y abre SEV1 si la cuenta ya no está activa o es el plan gratuito.
* BE-051 (PM-01-02) cuenta cada intento por endpoint, carril y trabajo en `raw.provider_endpoint_usage`: un día así se vería por endpoint
  aunque `api_calls` no lo recoja.

## 2. 619.351 archivos RAW y 330.337 filas de índice

Medido de nuevo el 20-nov-2026 a las 01:48 UTC (ha crecido desde el 19-nov): **622.247 archivos** en `/srv/predigol/raw` (todos
`.json.gz`: 622.227 de API-Football y 20 CSV de football-data.co.uk) y **331.219 filas** en `raw.ingestion_payloads`.

| Clase | Archivos | Tamaño |
| --- | --- | --- |
| En la ruta exacta de una fila del índice | **331.219** | 2.780,7 MB |
| **El mismo cuerpo ya indexado, guardado otra vez en la carpeta de otro día** | **290.984** | 363,1 MB |
| Sin fila en el índice | **44** | 3,0 MB |
| Filas del índice sin archivo | **0** | — |

622.247 − 331.219 = 291.028 = 290.984 + 44.

**Causa:** el almacén guarda cada respuesta en `api-football/AAAA/MM/DD/<endpoint>__<hash12>.json.gz`
(`fbi.storage.payload_store`): **la fecha de la petición forma parte de la ruta**. El índice tiene como clave el hash del cuerpo y se
escribe con `ON CONFLICT (hash) DO NOTHING` (`RunLedger.record_payloads`): guarda cada cuerpo **una sola vez**, con la ruta del primer
día. Cuando un trabajo vuelve a pedir lo mismo otro día y el proveedor contesta exactamente igual, el archivo se escribe de nuevo en la
carpeta de ese día y el índice no añade fila. No se pierde nada ni falta nada: toda fila tiene su archivo y casi todo archivo tiene su
cuerpo en el índice.

Quién repite (archivos repetidos por endpoint): `players-teams` 123.240 · `teams-statistics` 51.040 · `coachs` 29.440 · `fixtures` 12.700 ·
`players-squads` 11.979 · `players` 11.739 · `fixtures-rounds` 10.989 · `transfers` 5.722 · `predictions` 5.437 · `injuries` 4.985 ·
`standings` 3.968 · los cuatro de líderes ≈ 3.900 cada uno · `odds` 2.164 · resto < 1.000. Es la pasada semanal de referencia
(`reference_refresh`) y el contexto, que vuelven a pedir datos que no cambian.

Los 44 sin índice: 13 de `/status` (no abre ejecución, por diseño), 8 de `odds-live` (octubre),
16 de `fixtures`, 4 de `teams`, 2 de `odds` y 1 de `leagues`, probablemente de ejecuciones que fallaron entre guardar el archivo e indexarlo (no se comprobó una a una).
Repartidos en 15 días, nunca más de 8 en uno.

**Lectura:** el «casi el doble» son copias del mismo cuerpo: 363 MB, un 8 % de los 4,6 GB del RAW, y crecen con cada pasada semanal.
No se borra nada (regla 2 de la auditoría). Si se quiere evitar, las opciones son guardar el cuerpo una sola vez por hash (sin la fecha en
la ruta) o enlazar el archivo repetido al primero; es una decisión de almacenamiento para otra tarea, no de esta.

### `audit.storage_cleanups`

Seis filas, todas del 6-oct-2026 entre las 23:24 y las 23:40 UTC: el archivo y la purga de las cuotas en vivo (revisiones 0068 y 0069),
incluidas 7.167 respuestas `/odds/live` (168 MB) borradas del RAW tras archivarlas en `raw/odds-live.tar`. Ninguna limpieza después:
no explican la diferencia de archivos ni el 29-oct.

## Consultas (solo lectura)

Se ejecutaron por SSH desde el portátil, en `docker exec predigol-postgres psql -U postgres -d fbi` con
`SET default_transaction_read_only=on; SET statement_timeout='90s'`, el 20-nov-2026 entre las 01:47:19 y las 01:48:54 UTC, con el servidor
tranquilo (la cadena del despliegue anterior ya en `deployed`, fuera de las ventanas de copia y de `fixtures_sync`).

```sql
-- el libro y lo que reclaman las ejecuciones, por día
WITH l AS (SELECT started_at::date d, sum(api_calls) calls, count(*) runs FROM raw.ingestion_runs
            WHERE started_at >= '2026-10-20' AND started_at < '2026-11-20' GROUP BY 1)
SELECT q.quota_date, q.spent, l.calls, q.spent - coalesce(l.calls, 0) AS sin_reclamar
  FROM raw.provider_quota q LEFT JOIN l ON l.d = q.quota_date
 WHERE q.quota_date BETWEEN '2026-10-20' AND '2026-11-19' ORDER BY 1;

-- el 29-oct por trabajo y estado
SELECT job_type, status, count(*), sum(api_calls), sum(payloads_stored), sum(errors)
  FROM raw.ingestion_runs WHERE started_at >= '2026-10-29' AND started_at < '2026-10-30'
 GROUP BY 1, 2 ORDER BY 4 DESC NULLS LAST;

-- cuándo empezó y acabó la respuesta de plan gratuito
SELECT min(started_at), max(started_at), count(*) FROM raw.ingestion_runs
 WHERE started_at >= '2026-10-27' AND started_at < '2026-11-02'
   AND (last_error ILIKE '%request limit for the day%' OR last_error ILIKE '%Free plans%');

-- la hora en que se agotó el presupuesto propio
SELECT quota_date, spent, budget, updated_at FROM raw.provider_quota WHERE quota_date = '2026-10-29';

-- limpiezas del almacén
SELECT id, kind, subject, rows, bytes, verified, recorded_at FROM audit.storage_cleanups ORDER BY id;
```

Archivos frente al índice: la lista de rutas del índice (`COPY (SELECT file_path, left(hash,12), endpoint, provider FROM
raw.ingestion_payloads) TO STDOUT`) y la de archivos (`nice -n 19 ionice -c3 find /srv/predigol/raw -type f -printf '%P|%s\n'`), en un
directorio temporal propio de `/tmp` que se borró al terminar, y un cruce con `awk`: un archivo está «en el índice» si su ruta es la de
una fila; «mismo cuerpo otro día» si su nombre (`<endpoint>__<hash12>`) es el de una fila con otra ruta; «sin índice» en otro caso.

## Vuelta atrás

No hay nada que revertir: solo se leyó. Los archivos temporales del servidor (`/tmp/pm0103_files.*`) se borraron hacia las 01:51 UTC; dentro
del contenedor de PostgreSQL no se escribió nada. No se gastó ninguna petición al proveedor.
